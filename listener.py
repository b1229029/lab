import asyncio
import json
import os
import tempfile
import time
import numpy as np
import websockets
import functools
from pydub import AudioSegment

# 👇 引入我們所有的外部服務 (Services)
from services.calendar_service import create_google_calendar_event
from services.ai_service import (
    analyze_image_content,
    summarize_chunk,
    generate_meeting_summary,
    generate_interim_summary  # 👈 新增引入這個即時重點函式
)
from services.audio_service import (
    whisper_model, cc, analyzer, remove_overlap_text, AgendaMonitor, DEVICE
)

# ==========================================
# 全域設定 (僅保留 WebSocket 與音訊處理參數)
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

    try:
        async for message in websocket:
            if isinstance(message, str):
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')
                    if msg_type == 'setup_agenda':
                        user_topics = data.get('topics', [])
                        current_monitor = AgendaMonitor(user_topics)
                        
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
                            for idx, summary in enumerate(ai_interim_summaries): compiled_context += f"第 {idx+1} 階段：\n{summary}\n\n"
                        tail_transcript = ai_transcript_log[last_interim_index:]
                        if tail_transcript.strip(): compiled_context += f"【會議尾聲未總結之逐字稿】\n{tail_transcript}"
                        if not ai_interim_summaries: compiled_context = ai_transcript_log

                        undiscussed_topics = []
                        if current_monitor: undiscussed_topics = current_monitor.get_undiscussed_topics()
                        loop = asyncio.get_running_loop()
                        json_result = await loop.run_in_executor(None, generate_meeting_summary, compiled_context, undiscussed_topics, template_type)
                        
                        res_dict = json.loads(json_result)
                        if "error" in res_dict: await websocket.send(json.dumps({"type": "error", "message": res_dict["error"]}))
                        else: await websocket.send(json.dumps({"type": "summary_result", "data": json_result}))
                    
                    elif msg_type == 'request_interim_summary':
                        current_log_len = len(ai_transcript_log)
                        recent_transcript = ai_transcript_log[last_interim_index:current_log_len]
                        last_interim_index = current_log_len 
                        
                        # 👈 改由直接呼叫 ai_service 內的函式
                        loop = asyncio.get_running_loop()
                        interim_text = await loop.run_in_executor(None, generate_interim_summary, recent_transcript)
                        
                        if "無新增" not in interim_text and "未回傳內容" not in interim_text and "伺服器錯誤" not in interim_text and "生成失敗" not in interim_text and "目前內容過少" not in interim_text:
                            ai_interim_summaries.append(interim_text)
                            
                        await websocket.send(json.dumps({"type": "interim_summary_result", "data": interim_text}))

                    elif msg_type == 'analyze_image':
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
                        await websocket.send(json.dumps({"type": "upload_progress", "message": "Whisper 轉錄中 (可能需要幾分鐘)..."}))
                        try:
                            loop = asyncio.get_running_loop()
                            dynamic_prompt = "我們正在討論一般會議。繁體中文。"
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
                                
                            CHUNK_SIZE = 1000
                            compiled_context = ""
                            if len(ai_transcript_log) > CHUNK_SIZE:
                                await websocket.send(json.dumps({"type": "upload_progress", "message": "文字量較大，啟動自動分段防爆處理..."}))
                                chunks = [ai_transcript_log[i:i+CHUNK_SIZE] for i in range(0, len(ai_transcript_log), CHUNK_SIZE)]
                                ai_file_interim_summaries = []
                                for idx, chunk in enumerate(chunks):
                                    await websocket.send(json.dumps({"type": "upload_progress", "message": f"正在總結第 {idx+1}/{len(chunks)} 段內容..."}))
                                    chunk_summary = await loop.run_in_executor(None, summarize_chunk, chunk)
                                    if "無明顯重點" not in chunk_summary and "總結失敗" not in chunk_summary: ai_file_interim_summaries.append(chunk_summary)
                                if ai_file_interim_summaries:
                                    compiled_context = "【各階段重點回顧】\n"
                                    for idx, summary in enumerate(ai_file_interim_summaries): compiled_context += f"第 {idx+1} 階段：\n{summary}\n\n"
                                else: compiled_context = ai_transcript_log[-1500:]
                            else: compiled_context = ai_transcript_log

                            await websocket.send(json.dumps({"type": "upload_progress", "message": "正在生成最終總結報告與心智圖..."}))
                            undiscussed_topics = []
                            if current_monitor: undiscussed_topics = current_monitor.get_undiscussed_topics()
                            json_result = await loop.run_in_executor(None, generate_meeting_summary, compiled_context, undiscussed_topics, "general")
                            res_dict = json.loads(json_result)
                            if "error" in res_dict: await websocket.send(json.dumps({"type": "error", "message": res_dict["error"]}))
                            else: await websocket.send(json.dumps({"type": "summary_result", "data": json_result}))
                        except Exception as e: await websocket.send(json.dumps({"type": "error", "message": str(e)}))
                        finally:
                            if upload_file_path and os.path.exists(upload_file_path): os.remove(upload_file_path)
                            is_file_mode = False
                except Exception as e: print(f"JSON Error: {e}")
                continue 
            else:
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
                        
                        dynamic_prompt = "我們正在討論一般會議。繁體中文。"
                        result = whisper_model.transcribe(samples_to_process, language="zh", fp16=(DEVICE == "cuda"), initial_prompt=dynamic_prompt)
                        
                        clean_text_parts = []
                        for segment in result['segments']:
                            if segment['end'] > overlap_offset: clean_text_parts.append(cc.convert(segment['text']))
                        pure_new_text = "".join(clean_text_parts)
                        final_clean_text = remove_overlap_text(server_clean_buffer, pure_new_text)
                        
                        if final_clean_text.strip():
                            server_clean_buffer += final_clean_text
                            
                            cut_length = len(pure_new_text) - len(final_clean_text)
                            current_len = 0
                            first_segment_time = None
                            
                            for segment in result['segments']:
                                if segment['end'] > overlap_offset:
                                    text = cc.convert(segment['text'])
                                    current_len += len(text)
                                    if current_len > cut_length: 
                                        abs_time = cumulative_audio_seconds - overlap_offset + segment['start']
                                        first_segment_time = max(0, int(abs_time))
                                        break
                            
                            if first_segment_time is None:
                                first_segment_time = int(cumulative_audio_seconds)
                                
                            m, s = divmod(first_segment_time, 60)
                            ts_str = f"[{m:02d}:{s:02d}] "
                            
                            hit_topics = []
                            if current_monitor: hit_topics = current_monitor.check_transcript(final_clean_text)
                            discussion_status = analyzer.analyze(final_clean_text)
                            
                            tagged_segment = ts_str + final_clean_text
                            if discussion_status == "DISPUTE": tagged_segment = f"{ts_str}(系統偵測：爭議) {final_clean_text}"
                            elif discussion_status == "CONSENSUS": tagged_segment = f"{ts_str}(系統偵測：共識) {final_clean_text}"
                            
                            ai_transcript_log += tagged_segment + "\n"
                            warning_msg = ""
                            if current_monitor:
                                undiscussed = current_monitor.get_undiscussed_topics()
                                if (time.time() - current_monitor.start_time > 60) and undiscussed and (time.time() - current_monitor.last_remind_time > 30):
                                     warning_msg = f"⚠️ 提醒尚未討論：{', '.join(undiscussed)}"
                                     current_monitor.last_remind_time = time.time()
                            
                            await websocket.send(json.dumps({"type": "transcript", "text": final_clean_text, "ts": ts_str, "hit_topics": hit_topics, "status": discussion_status, "warning": warning_msg}))
                        
                        cumulative_audio_seconds += chunk_duration
                    except Exception as e: print(f"處理錯誤: {e}")
                    finally:
                        if os.path.exists(temp_webm_path): os.remove(temp_webm_path)
    except websockets.exceptions.ConnectionClosed:
        print("連線關閉")
        if upload_file_handle: upload_file_handle.close()

async def main():
    print(f"🚀 WebSocket 啟動於 ws://{WS_HOST}:{WS_PORT}")
    async with websockets.serve(audio_handler, WS_HOST, WS_PORT, max_size=None, ping_interval=None):
        await asyncio.Future()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass