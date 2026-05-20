import asyncio
import json
import os
import tempfile
import time
import numpy as np
import websockets
import functools
from pydub import AudioSegment

# 👇 引入外部服務 (Services)
from services.calendar_service import create_google_calendar_event
from services.ai_service import (
    analyze_image_content, # 僅保留單次辨識功能，不存入總結
    summarize_chunk,
    generate_meeting_summary,
    generate_interim_summary
)
from services.audio_service import (
    whisper_model, cc, analyzer, remove_overlap_text, AgendaMonitor, DEVICE
)

# ==========================================
# 全域設定
# ==========================================
OVERLAP_DURATION_MS = 10000
WS_HOST = "0.0.0.0"
WS_PORT = 8765
SILENCE_THRESHOLD = -35

async def audio_handler(websocket):
    current_monitor = None
    server_clean_buffer = ""
    ai_transcript_log = ""
    ai_interim_summaries = []
    last_interim_index = 0  
    last_audio_segment = None
    is_file_mode = False
    upload_file_handle = None
    upload_file_path = None
    cumulative_audio_seconds = 0.0 

    # 🚀 人名辨識關鍵：初始化當前會議的參與者名單變數
    current_participants = ""

    try:
        async for message in websocket:
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')
                    if msg_type == 'setup_agenda':
                        user_topics = data.get('topics', [])
                        current_monitor = AgendaMonitor(user_topics)
                        
                        # 🚀 接收前端傳來的參與者名單
                        current_participants = data.get('participants', "")

                        server_clean_buffer = ""
                        ai_transcript_log = ""
                        ai_interim_summaries = []
                        last_interim_index = 0  
                        last_audio_segment = None
                        cumulative_audio_seconds = 0.0 
                        
                        await websocket.send(json.dumps({"type": "agenda_ready", "topics": user_topics}))
                    
                    elif msg_type == 'request_summary':
                        template_type = data.get('template', 'general')
                        compiled_context = ""
                        
                        if ai_interim_summaries:
                            compiled_context += "【各階段重點回顧】\n"
                            for idx, summary in enumerate(ai_interim_summaries): 
                                compiled_context += f"第 {idx+1} 階段：\n{summary}\n\n"
                        
                        compiled_context += f"【完整會議逐字稿】\n{ai_transcript_log}"

                        undiscussed_topics = []
                        if current_monitor: undiscussed_topics = current_monitor.get_undiscussed_topics()
                        loop = asyncio.get_running_loop()

                        # 將 current_participants 傳遞給 AI 總結，確保總結時人名也正確
                        json_result = await loop.run_in_executor(
                            None, 
                            generate_meeting_summary, 
                            compiled_context, 
                            undiscussed_topics, 
                            template_type,
                            0, 
                            current_participants 
                        )

                        res_dict = json.loads(json_result)
                        if "error" in res_dict: await websocket.send(json.dumps({"type": "error", "message": res_dict["error"]}))
                        else: await websocket.send(json.dumps({"type": "summary_result", "data": json_result}))
                    
                    elif msg_type == 'request_interim_summary':
                        current_log_len = len(ai_transcript_log)
                        recent_transcript = ai_transcript_log[last_interim_index:current_log_len]
                        last_interim_index = current_log_len 
                        
                        loop = asyncio.get_running_loop()
                        interim_text = await loop.run_in_executor(None, generate_interim_summary, recent_transcript)
                        
                        if "無新增" not in interim_text:
                            ai_interim_summaries.append(interim_text)
                            
                        await websocket.send(json.dumps({"type": "interim_summary_result", "data": interim_text}))

                    elif msg_type == 'analyze_image':
                        # 僅執行單次辨識並回傳，不儲存至全域 image_logs
                        base64_data = data.get('image_data', '')
                        filename = data.get('filename', 'image.jpg')
                        if base64_data.startswith('data:image'): base64_data = base64_data.split(',')[1]
                        await websocket.send(json.dumps({"type": "upload_progress", "message": "正在分析圖片內容..."}))
                        loop = asyncio.get_running_loop()
                        analysis_result = await loop.run_in_executor(None, analyze_image_content, base64_data, filename)
                        await websocket.send(json.dumps({"type": "image_analysis_result", "description": analysis_result}))

                    elif msg_type == 'schedule_next':
                        try:
                            loop = asyncio.get_running_loop()
                            event_link = await loop.run_in_executor(None, create_google_calendar_event, data.get('topic'), data.get('description'), data.get('datetime'), data.get('emails'))
                            await websocket.send(json.dumps({"type": "schedule_success", "link": event_link}))
                        except Exception as e: await websocket.send(json.dumps({"type": "error", "message": str(e)}))
                            
                    elif msg_type == 'start_file_upload':
                        is_file_mode = True
                        upload_file_handle = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
                        upload_file_path = upload_file_handle.name
                    
                    elif msg_type == 'end_file_upload':
                        if upload_file_handle: upload_file_handle.close()
                        await websocket.send(json.dumps({"type": "upload_progress", "message": "Whisper 轉錄中..."}))
                        try:
                            loop = asyncio.get_running_loop()

                            # 🚀 (檔案模式) 將參與者名單加入 Whisper Prompt
                            base_prompt = "我們正在討論一般會議。繁體中文。"
                            dynamic_prompt = f"{base_prompt} 本次會議參與者有：{current_participants}。" if current_participants else base_prompt

                            run_transcribe = functools.partial(whisper_model.transcribe, upload_file_path, language="zh", fp16=(DEVICE == "cuda"), initial_prompt=dynamic_prompt)
                            result = await loop.run_in_executor(None, run_transcribe)
                            
                            for segment in result['segments']:
                                text = cc.convert(segment['text'])
                                if not text.strip(): continue
                                start_time = int(segment['start'])
                                m, s = divmod(start_time, 60)
                                ts_str = f"[{m:02d}:{s:02d}] "
                                hit_topics = []
                                if current_monitor: hit_topics = current_monitor.check_transcript(text)
                                disc_status = analyzer.analyze(text)
                                tag_text = ts_str + text
                                if disc_status == "DISPUTE": tag_text = f"{ts_str}(系統偵測：爭議) {text}"
                                elif disc_status == "CONSENSUS": tag_text = f"{ts_str}(系統偵測：共識) {text}"
                                ai_transcript_log += tag_text + "\n"
                                await websocket.send(json.dumps({"type": "transcript", "text": text, "ts": ts_str, "hit_topics": hit_topics, "status": disc_status}))
                                await asyncio.sleep(0.01)
                                
                            # 產出總結流程省略... (同你原始碼)
                            CHUNK_SIZE = 1000
                            compiled_context = ai_transcript_log # 簡化處理
                            await websocket.send(json.dumps({"type": "upload_progress", "message": "正在生成總結..."}))
                            undiscussed_topics = []
                            if current_monitor: undiscussed_topics = current_monitor.get_undiscussed_topics()
                            
                            json_result = await loop.run_in_executor(None, generate_meeting_summary, compiled_context, undiscussed_topics, "general", 0, current_participants)
                            await websocket.send(json.dumps({"type": "summary_result", "data": json_result}))

                        except Exception as e: await websocket.send(json.dumps({"type": "error", "message": str(e)}))
                        finally:
                            if upload_file_path and os.path.exists(upload_file_path): os.remove(upload_file_path)
                            is_file_mode = False
                except Exception as e: print(f"JSON Error: {e}")
                continue 
            else:
                # 二進位音訊處理
                if is_file_mode:
                    if upload_file_handle: upload_file_handle.write(message)
                else:
                    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as temp_webm:
                        temp_webm.write(message)
                        temp_webm_path = temp_webm.name
                    try:
                        current_audio_chunk = AudioSegment.from_file(temp_webm_path)
                        if current_audio_chunk.dBFS < SILENCE_THRESHOLD: continue
                        
                        chunk_duration = current_audio_chunk.duration_seconds
                        current_audio_chunk = current_audio_chunk.set_frame_rate(16000).set_channels(1).set_sample_width(2)
                        samples_current = np.array(current_audio_chunk.get_array_of_samples()).astype(np.float32) / 32768.0
                        samples_to_process = samples_current
                        overlap_offset = 0.0
                        
                        if last_audio_segment is not None:
                            prefix_segment = last_audio_segment[-OVERLAP_DURATION_MS:]
                            samples_prefix = np.array(prefix_segment.get_array_of_samples()).astype(np.float32) / 32768.0
                            samples_to_process = np.concatenate((samples_prefix, samples_current))
                            overlap_offset = len(prefix_segment) / 1000.0
                        last_audio_segment = current_audio_chunk

                        # 🚀 (即時模式) 將參與者名單加入 Whisper Prompt
                        base_prompt = "我們正在討論一般會議。繁體中文。"
                        dynamic_prompt = f"{base_prompt} 本次會議參與者有：{current_participants}。" if current_participants else base_prompt
                        
                        loop = asyncio.get_running_loop()
                        run_transcribe = functools.partial(whisper_model.transcribe, samples_to_process, language="zh", fp16=(DEVICE == "cuda"), initial_prompt=dynamic_prompt)
                        result = await loop.run_in_executor(None, run_transcribe)
                        
                        clean_text_parts = []
                        for segment in result['segments']:
                            if segment['end'] > overlap_offset: clean_text_parts.append(cc.convert(segment['text']))
                        pure_new_text = "".join(clean_text_parts)
                        final_clean_text = remove_overlap_text(server_clean_buffer, pure_new_text)
                        
                        if final_clean_text.strip():
                            server_clean_buffer += final_clean_text
                            abs_time = cumulative_audio_seconds # 簡化時間戳
                            m, s = divmod(int(abs_time), 60)
                            ts_str = f"[{m:02d}:{s:02d}] "
                            
                            hit_topics = []
                            if current_monitor: hit_topics = current_monitor.check_transcript(final_clean_text)
                            discussion_status = analyzer.analyze(final_clean_text)
                            ai_transcript_log += ts_str + final_clean_text + "\n"
                            
                            await websocket.send(json.dumps({"type": "transcript", "text": final_clean_text, "ts": ts_str, "hit_topics": hit_topics, "status": discussion_status}))
                        
                        cumulative_audio_seconds += chunk_duration
                    except Exception as e: print(f"處理錯誤: {e}")
                    finally:
                        if os.path.exists(temp_webm_path): os.remove(temp_webm_path)
    except websockets.exceptions.ConnectionClosed:
        print("連連線關閉")

async def main():
    print(f"🚀 WebSocket 啟動於 ws://{WS_HOST}:{WS_PORT}")
    async with websockets.serve(audio_handler, WS_HOST, WS_PORT, max_size=None, ping_interval=None):
        await asyncio.Future()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass