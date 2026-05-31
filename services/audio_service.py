"""音訊辨識與議程分析服務。

本檔在伺服器啟動時載入 Whisper 語音辨識模型、句向量模型與簡繁轉換器，
並提供三類能力：
1. 判斷逐字稿片段是否偏向共識或爭議。
2. 移除串流音訊重疊辨識造成的重複文字。
3. 監控會議議程是否已被討論。

注意：模型載入成本高，因此在模組層級初始化一次，讓 listener.py 的每個
WebSocket 連線共用同一組模型。
"""

import time
import difflib
import torch
import whisper
import opencc
from sentence_transformers import SentenceTransformer, util

# ==========================================
# 1. 模型全域設定
# ==========================================
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
WHISPER_MODEL_SIZE = "medium"
EMBEDDING_MODEL_NAME = 'BAAI/bge-m3'

# ==========================================
# 2. 載入模型 (程式啟動時執行一次)
# ==========================================
print(f"正在 {DEVICE} 上載入 Whisper 模型 ({WHISPER_MODEL_SIZE})...")
whisper_model = whisper.load_model(WHISPER_MODEL_SIZE, device=DEVICE)
print("✅ Whisper 模型載入完成。")

print(f"⏳ 正在載入 Embedding 模型 ({EMBEDDING_MODEL_NAME})...")
embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
print("✅ Embedding 模型載入完成！")

# 繁簡轉換器
cc = opencc.OpenCC('s2t')

# ==========================================
# 3. 語意與議程分析模組
# ==========================================
class DiscussionAnalyzer:
    """用關鍵字快速標記討論狀態。

    這不是語意模型，而是輕量規則：若片段出現爭議關鍵字就標為 DISPUTE，
    出現同意或結論關鍵字就標為 CONSENSUS，否則維持 NEUTRAL。前端會依
    狀態加上不同顏色與標籤，方便使用者掃描會議過程。
    """

    def __init__(self):
        self.dispute_keywords = ["可是", "不過", "但我", "但是", "反對", "疑慮", "不太好", "風險", "再想想", "不同意", "有問題", "修一下", "調整一下", "不是很", "不贊成", "擔心"]
        self.consensus_keywords = ["結論是", "就這樣", "沒問題", "同意", "贊成", "定案", "確認", "好的", "OK", "ok", "採用", "通過", "沒有意見", "不錯", "共識"]

    def analyze(self, text):
        """分析單段文字並回傳 DISPUTE、CONSENSUS 或 NEUTRAL。"""
        if not text: return "NEUTRAL"
        for kw in self.dispute_keywords:
            if kw in text: return "DISPUTE"
        for kw in self.consensus_keywords:
            if kw in text: return "CONSENSUS"
        return "NEUTRAL"

# 建立一個全域的分析器實例供外部使用
analyzer = DiscussionAnalyzer()

def remove_overlap_text(previous_text, new_text):
    """移除串流音訊切片之間的重複辨識文字。

    即時錄音每 30 秒會送一段音訊到 Whisper，伺服器也會附上前一段尾端
    作為 overlap 來提升斷句品質。這會讓新片段開頭可能重複前文，因此以
    SequenceMatcher 比對前文尾巴與新文開頭，找到高度相似處後切掉重複字。
    """
    if not previous_text or not new_text: return new_text
    check_len = min(len(previous_text), 100)
    suffix = previous_text[-check_len:]
    max_overlap = min(len(suffix), len(new_text))
    for i in range(max_overlap, 2, -1):
        matcher = difflib.SequenceMatcher(None, suffix[-i:], new_text[:i])
        if matcher.ratio() > 0.75: return new_text[i:]
    return new_text

class AgendaMonitor:
    """使用句向量比對追蹤議程是否被提到。

    初始化時先把使用者輸入的 agenda topics 編成 embedding；之後每收到
    一段逐字稿，就計算該段與所有議程的 cosine similarity。若相似度超過
    門檻，該議程會被標記為已討論。
    """

    def __init__(self, topics):
        self.topics = topics
        self.topic_embeddings = embedding_model.encode(topics, convert_to_tensor=True)
        self.status = {t: False for t in topics}
        self.start_time = time.time()
        self.last_remind_time = time.time()

    def check_transcript(self, text_segment):
        """檢查逐字稿片段命中的議程，並回傳本次新命中的 topic 清單。"""
        if not text_segment or len(text_segment) < 2: return []
        text_embedding = embedding_model.encode(text_segment, convert_to_tensor=True)
        cos_scores = util.pytorch_cos_sim(text_embedding, self.topic_embeddings)[0]
        hit_topics = []
        for idx, score in enumerate(cos_scores):
            if score > 0.45:
                topic = self.topics[idx]
                if not self.status[topic]:
                    self.status[topic] = True
                    hit_topics.append(topic)
        return hit_topics
    
    def get_undiscussed_topics(self): 
        """回傳尚未被逐字稿命中的議程，供摘要階段提醒使用者。"""
        return [t for t, d in self.status.items() if not d]
