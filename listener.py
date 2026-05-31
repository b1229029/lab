"""WebSocket 即時會議處理器。

前端 record.js 會連到本檔開的 ws://host:8765。此服務同時處理兩種資料：
1. JSON 控制訊息，例如設定議程、要求摘要、圖片分析、建立下次會議。
2. 二進位音訊片段，例如即時麥克風錄音與整個音訊檔上傳。

辨識、摘要、圖片分析與行事曆建立都是阻塞型工作，因此會透過
run_in_executor 丟到背景執行，避免卡住 WebSocket 收發。
"""

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
    """處理單一前端 WebSocket 連線的完整會議生命週期。

    每個連線都維護自己的逐字稿、議程監控器、即時摘要與上傳暫存檔。
    前端重新整理或中斷連線後，這些記憶體狀態會自然釋放。
    """
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
                # 字串訊息一律視為 JSON 控制事件；不同 type 代表不同前端動作。
                try:
                    data = json.loads(message)
                    msg_type = data.get('type')
                    if msg_type == 'setup_agenda':
                        # 會議開始前先鎖定議程與與會者，後續辨識可用於議程命中與 AI prompt。
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
                        # 會議結束或使用者手動要求時，整理目前累積的所有上下文產生總摘要。
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
                        # 只摘要上次 interim 之後新增的逐字稿，避免重複摘要相同內容。
                        current_log_len = len(ai_transcript_log)
                        recent_transcript = ai_transcript_log[last_interim_index:current_log_len]
                        last_interim_index = current_log_len 
                        
                        loop = asyncio.get_running_loop()
                        interim_text = await loop.run_in_executor(None, generate_interim_summary, recent_transcript)
                        
                        if "無新增" not in interim_text:
                            ai_interim_summaries.append(interim_text)
                            
                        await websocket.send(json.dumps({"type": "interim_summary_result", "data": interim_text}))

                    elif msg_type == 'analyze_image':
                        # 圖片分析會先回傳進度，避免前端在模型處理時看起來沒有反應。
                        # 僅執行單次辨識並回傳，不儲存至全域 image_logs
                        base64_data = data.get('image_data', '')
                        filename = data.get('filename', 'image.jpg')
                        if base64_data.startswith('data:image'): base64_data = base64_data.split(',')[1]
                        await websocket.send(json.dumps({"type": "upload_progress", "message": "正在分析圖片內容..."}))
                        loop = asyncio.get_running_loop()
                        analysis_result = await loop.run_in_executor(None, analyze_image_content, base64_data, filename)
                        await websocket.send(json.dumps({"type": "image_analysis_result", "filename": filename, "description": analysis_result}))

                    elif msg_type == 'schedule_next':
                        # 使用 AI 建議的下次議程與使用者輸入的時間建立 Google Calendar 事件。
                        try:
                            loop = asyncio.get_running_loop()
                            event_link = await loop.run_in_executor(None, create_google_calendar_event, data.get('topic'), data.get('description'), data.get('datetime'), data.get('emails'))
                            await websocket.send(json.dumps({"type": "schedule_success", "link": event_link}))
                        except Exception as e: await websocket.send(json.dumps({"type": "error", "message": str(e)}))

                    # 接收前端送來的圖片結果
                    elif msg_type == 'append_image_result':
                        # 將已完成的圖片分析結果寫入逐字稿累積文字，使總摘要與 RAG 都能看到。
                        img_filename = data.get('filename', '圖片')
                        img_description = data.get('description', '')
                        
                        # 1. 將圖片結果加入到後端的總結日誌中 
                        # (注意：字眼必須包含你在 ai_service.py 中要求的 [圖片分析]，才能觸發強制指示)
                        tag_text = f"\n[圖片分析] {img_filename}:\n{img_description}\n"
                        ai_transcript_log += tag_text
                        
                        # 2. 偽裝成一般的逐字稿訊息送回前端，讓 record.js 正常把它存入陣列並渲染，就不會被洗掉了
                        await websocket.send(json.dumps({
                            "type": "transcript",
                            "text": f"🖼️ 【圖片分析】 {img_filename} - {img_description}",
                            "ts": "[系統補充] ",
                            "hit_topics": [],
                            "status": "NORMAL",
                            "image_analysis": {
                                "filename": img_filename,
                                "description": img_description
                            }
                        }))
                            
                    elif msg_type == 'start_file_upload':
                        # 大檔音訊以上傳模式處理：前端分塊傳送，後端先寫入暫存 webm。
                        is_file_mode = True
                        upload_file_handle = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
                        upload_file_path = upload_file_handle.name
                    
                    elif msg_type == 'end_file_upload':
                        # 檔案上傳完成後一次交給 Whisper 轉錄，再產生總摘要。
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
                # 二進位訊息是音訊資料。檔案模式直接寫入暫存檔；麥克風模式立即轉錄。
                # 二進位音訊處理
                if is_file_mode:
                    if upload_file_handle: upload_file_handle.write(message)
                else:
                    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as temp_webm:
                        temp_webm.write(message)
                        temp_webm_path = temp_webm.name
                    try:
                        current_audio_chunk = AudioSegment.from_file(temp_webm_path)
                        # 音量低於門檻視為靜音，跳過可減少 Whisper 無效推論。
                        if current_audio_chunk.dBFS < SILENCE_THRESHOLD: continue
                        
                        chunk_duration = current_audio_chunk.duration_seconds
                        current_audio_chunk = current_audio_chunk.set_frame_rate(16000).set_channels(1).set_sample_width(2)
                        samples_current = np.array(current_audio_chunk.get_array_of_samples()).astype(np.float32) / 32768.0
                        samples_to_process = samples_current
                        overlap_offset = 0.0
                        
                        if last_audio_segment is not None:
                            # 附上前一段尾端當作上下文，提升切片邊界附近的辨識品質。
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
    """啟動 WebSocket server 並保持事件迴圈常駐。"""
    print(f"🚀 WebSocket 啟動於 ws://{WS_HOST}:{WS_PORT}")
    async with websockets.serve(audio_handler, WS_HOST, WS_PORT, max_size=None, ping_interval=None):
        await asyncio.Future()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
