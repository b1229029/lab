import time
import requests
import json

# ==========================================
# API 相關設定
# ==========================================
NEW_API_KEY = "sk-15792e507fa044594bb0670f0469c77188821b8bc139e5dd"
BASE_URL = "https://air.cgu.edu.tw/cgullmapi/v1"
CHAT_MODEL = "gpt-oss:20b"
CHAT_ENDPOINT = f"{BASE_URL}/chat/completions"

# ==========================================
# 圖片分析功能
# ==========================================
def analyze_image_content(base64_image, filename="unknown.jpg"):
    USE_MOCK_VISION = True 
    if USE_MOCK_VISION:
        time.sleep(1.5)
        return f"(系統暫存：已收到圖片 '{filename}'。目前模型尚未啟用視覺辨識，此為佔位描述。未來此處將顯示圖片的詳細分析。)"
    else:
        headers = {
            "Content-Type": "application/json", 
            "Authorization": f"Bearer {NEW_API_KEY}"
        }
        payload = {
            "model": "gpt-4o", 
            "messages": [
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": "請詳細描述這張圖片的內容"}, 
                        {"type": "image_url", "image_url": {"url": base64_image}}
                    ]
                }
            ], 
            "max_tokens": 500
        }
        try:
            response = requests.post(CHAT_ENDPOINT, headers=headers, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except Exception as e:
            return f"(圖片分析失敗 - {str(e)})"

# ==========================================
# 長文本分段總結
# ==========================================
def summarize_chunk(chunk_text):
    prompt = f"請幫我用 50 到 100 字以內的繁體中文，總結以下對話內容的重點。\n若這段內容無實質重點，請回覆：「無明顯重點」。\n【對話片段】\n{chunk_text}"
    headers = {
        "Content-Type": "application/json", 
        "Authorization": f"Bearer {NEW_API_KEY}"
    }
    payload = {
        "model": CHAT_MODEL, 
        "messages": [{"role": "user", "content": prompt}], 
        "max_tokens": 800, 
        "temperature": 0.2, 
        "stream": False 
    }
    try:
        res = requests.post(CHAT_ENDPOINT, headers=headers, json=payload, timeout=60)
        res.raise_for_status()
        return res.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        return "（此段落總結失敗）"

# ==========================================
# 生成最終會議紀錄與心智圖
# ==========================================
def generate_meeting_summary(compiled_context, undiscussed_list=None, template_type="general", retry_count=0):
    if not compiled_context or len(compiled_context) < 10: 
        return json.dumps({"summary": "會議內容過短，無法生成總結。", "mindmap": ""})

    if undiscussed_list is None: 
        undiscussed_list = []
    
    undiscussed_str = "、".join(undiscussed_list) if undiscussed_list else "無"

    templates = {
        "general": f"一、會議結論：\n二、尚未解決議題：(系統偵測「{undiscussed_str}」可能未討論)\n三、待辦事項：\n四、討論爭議點：\n"
    }
    selected_structure = templates.get(template_type, templates["general"])

    prompt = f"""
請扮演專業的會議秘書。你將收到一份「會議重點回顧」以及「會議素材(含時間)」。
請產出最終的完整會議紀錄。

⚠️【格式要求】請完全依照以下格式輸出，且務必在兩部分之間包含「===MINDMAP_START===」這行分隔符號！

【第一部分：會議重點紀錄】
{selected_structure}

===MINDMAP_START===
【第二部分：結構化心智圖】
(💡 指示：請參考【會議素材】中每句話開頭的 [MM:SS] 時間標記，將最相關的時間註記在心智圖節點後方。若找不到確切時間則保持空白，請勿自行發明時間)
# 本次會議核心主題
- 關鍵議題一 [00:10]
  - 細節說明 [00:45]

【會議素材】
{compiled_context}
"""

    headers = {
        "Content-Type": "application/json", 
        "Authorization": f"Bearer {NEW_API_KEY}"
    }
    
    payload = { 
        "model": CHAT_MODEL, 
        "messages": [{"role": "user", "content": prompt}], 
        "temperature": 0.3 + (0.1 * retry_count), 
        "max_tokens": 1500, 
        "stream": False 
    }

    try:
        response = requests.post(CHAT_ENDPOINT, headers=headers, json=payload, timeout=600)
        if response.status_code != 200: 
            return json.dumps({"error": f"伺服器錯誤 ({response.status_code})"})
        
        response.raise_for_status()
        raw_content = response.json()['choices'][0]['message']['content'].strip()
        
        if not raw_content:
            if retry_count < 2: 
                print(f"⚠️ 收到空白內容，啟動第 {retry_count + 1} 次重試...")
                return generate_meeting_summary(compiled_context, undiscussed_list, template_type, retry_count + 1)
            else: 
                return json.dumps({"error": "⚠️ API 連續回傳空白內容，請確認會議長度或稍後再試。"})

        summary_part = raw_content
        mindmap_part = ""
        
        if "===MINDMAP_START===" in raw_content:
            parts = raw_content.split("===MINDMAP_START===")
            summary_part = parts[0].strip()
            mindmap_part = parts[1].strip().replace("```markdown", "").replace("```", "").strip()
            if mindmap_part.startswith("【第二部分：結構化心智圖】"): 
                mindmap_part = mindmap_part.replace("【第二部分：結構化心智圖】", "").strip()
                
        return json.dumps({"summary": summary_part, "mindmap": mindmap_part})
    except Exception as e:
        return json.dumps({"error": f"生成錯誤: {str(e)}"})

# ==========================================
# 每分鐘即時重點 (Interim Summary)
# ==========================================
def generate_interim_summary(recent_transcript):
    if len(recent_transcript) < 30:
        return "目前內容過少，暫無重點。"
    
    prompt = f"請幫我用 50 字以內的繁體中文，條列式總結以下「最新這3分鐘」的對話內容。\n若無實質重點，請回覆：「無新增明顯重點」。\n【對話片段】\n{recent_transcript}"
    headers = {
        "Content-Type": "application/json", 
        "Authorization": f"Bearer {NEW_API_KEY}"
    }
    payload = { 
        "model": CHAT_MODEL, 
        "messages": [{"role": "user", "content": prompt}], 
        "temperature": 0.3, 
        "stream": False 
    }
    
    try:
        res = requests.post(CHAT_ENDPOINT, headers=headers, json=payload, timeout=30)
        if res.status_code != 200: 
            return f"(伺服器錯誤 {res.status_code})"
        res.raise_for_status()
        content = res.json()['choices'][0]['message']['content'].strip()
        return content if content else "（AI 未回傳內容）"
    except Exception as e:
        return f"生成失敗: {str(e)}"