import torch
import requests
import json
from sentence_transformers import util
from services.audio_service import embedding_model  # 重用 bge-m3 模型
from services.ai_service import CHAT_ENDPOINT, NEW_API_KEY, CHAT_MODEL

def chat_with_meeting_rag(question: str, full_transcript: str, summary_text: str, image_analysis_text: str = ""):
    image_section = ""
    if image_analysis_text:
        image_section = f"\n\n【圖片分析結果】\n{image_analysis_text}"

    searchable_text = (full_transcript or "") + image_section

    # 1. 將會議後完整的逐字稿與圖片分析結果，每 1000 字切成一塊
    chunk_size = 1000
    chunks = [searchable_text[i:i+chunk_size] for i in range(0, len(searchable_text), chunk_size)]
    
    # 如果內容很少，直接全給；如果很多，就進行 RAG 向量檢索
    if len(chunks) > 2:
        # 將「問題」與「所有切塊」轉成向量
        question_embedding = embedding_model.encode(question, convert_to_tensor=True)
        chunk_embeddings = embedding_model.encode(chunks, convert_to_tensor=True)
        
        # 計算餘弦相似度 (Cosine Similarity)
        cos_scores = util.pytorch_cos_sim(question_embedding, chunk_embeddings)[0]
        
        # 抓出最相關的前 3 個片段 (Top-K)
        top_k = min(3, len(chunks))
        top_results = torch.topk(cos_scores, k=top_k)
        retrieved_chunks = [chunks[idx] for idx in top_results[1]]
        retrieved_context = "\n...\n".join(retrieved_chunks)
    else:
        retrieved_context = searchable_text

    # 2. 組合終極 Prompt (將全局總結與局部細節結合)
    prompt = f"""
    你是一位專業的 AI 會議助理。請根據以下【會議重點總結】與【檢索出的對話細節】，回答使用者的問題。
    如果提供的資訊中沒有提到相關內容，請誠實回答「會議中未提及」，不要自行捏造。

    【會議重點總結 (幫助你掌握全局)】：
    {summary_text}

    【圖片分析結果 (會議中上傳圖片的內容，若與問題相關請一併引用)】：
    {image_analysis_text or "無"}

    【檢索出的對話細節 (幫助你尋找具體答案)】：
    {retrieved_context}

    【使用者的問題】：
    {question}
    """

    # 3. 呼叫你的 LLM API
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {NEW_API_KEY}"}
    payload = {
        "model": CHAT_MODEL, 
        "messages": [{"role": "user", "content": prompt}], 
        "temperature": 0.3, # 溫度調低，確保回答精準不幻想
        "stream": False 
    }
    
    try:
        res = requests.post(CHAT_ENDPOINT, headers=headers, json=payload, timeout=60)
        res.raise_for_status()
        return res.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"抱歉，機器人回答時發生錯誤：{str(e)}"
