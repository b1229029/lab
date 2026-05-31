"""會議資料 API。

此 router 管理單場會議的建立、查詢、更新、音訊上傳、刪除，以及針對已存
逐字稿與圖片分析內容進行 RAG 問答的端點。
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
import mysql.connector
import os
import shutil
from database import ensure_image_analysis_column, get_db_connection
from schemas import MeetingCreate, MeetingUpdate
from pydantic import BaseModel
from services.rag_service import chat_with_meeting_rag

router = APIRouter(tags=["會議管理"])

class ChatRequest(BaseModel):
    """RAG 問答端點的請求格式。"""
    question: str

def extract_image_analysis_from_transcript(transcript: str) -> str:
    """從逐字稿中萃取圖片分析紀錄。

    舊版流程會把圖片辨識結果插入逐字稿文字中；新版已有獨立欄位。
    這個函式用來支援舊資料，避免既有會議在查看或問答時遺失圖片資訊。
    """
    if not transcript:
        return ""

    entries = []
    for line in transcript.splitlines():
        if "圖片分析" in line:
            cleaned = line.strip()
            if cleaned and cleaned not in entries:
                entries.append(cleaned)
    return "\n".join(entries)

@router.post("/meetings")
def create_meeting(request: MeetingCreate):
    """在指定資料夾下建立一場新會議。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO meetings (folder_id, title) VALUES (%s, %s)", (request.folder_id, request.title))
        conn.commit()
        return {"message": "會議建立成功！", "meeting_id": cursor.lastrowid}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()

@router.get("/meetings/by_folder/{folder_id}")
def get_folder_meetings(folder_id: int):
    """取得某資料夾底下所有會議的列表資訊。"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, title, created_at, summary_text FROM meetings WHERE folder_id = %s ORDER BY created_at DESC", (folder_id,))
        return {"meetings": cursor.fetchall()}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()

@router.get("/meetings/{meeting_id}")
def get_single_meeting(meeting_id: int):
    """取得單場會議的完整資料，包含逐字稿、摘要、心智圖與檔案路徑。"""
    conn = get_db_connection()
    ensure_image_analysis_column(conn)
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM meetings WHERE id = %s", (meeting_id,))
        meeting = cursor.fetchone()
        if not meeting:
            raise HTTPException(status_code=404, detail="找不到這場會議")
        if not meeting.get("image_analysis_text"):
            meeting["image_analysis_text"] = extract_image_analysis_from_transcript(meeting.get("transcript_text", ""))
        return meeting
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()

@router.put("/meetings/{meeting_id}")
def save_meeting_results(meeting_id: int, request: MeetingUpdate):
    """儲存會議結束後產生的 AI 結果。"""
    conn = get_db_connection()
    ensure_image_analysis_column(conn)
    cursor = conn.cursor()
    try:
        image_analysis_text = request.image_analysis_text or extract_image_analysis_from_transcript(request.transcript_text or "")
        cursor.execute("""
            UPDATE meetings 
            SET transcript_text = %s, image_analysis_text = %s, summary_text = %s, mindmap_data = %s
            WHERE id = %s
        """, (request.transcript_text, image_analysis_text, request.summary_text, request.mindmap_data, meeting_id))
        conn.commit()
        return {"message": "會議紀錄已成功儲存到資料庫！"}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()

@router.post("/meetings/{meeting_id}/upload_audio")
def upload_meeting_audio(meeting_id: int, file: UploadFile = File(...)):
    """接收前端上傳的完整音訊檔，並把路徑寫回 meetings 表。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        file_extension = file.filename.split(".")[-1] if "." in file.filename else "webm"
        file_path = f"uploads/meeting_{meeting_id}.{file_extension}"
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        cursor.execute("UPDATE meetings SET audio_file_path = %s WHERE id = %s", (file_path, meeting_id))
        conn.commit()
        return {"message": "音檔上傳成功", "path": file_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"儲存音檔失敗: {e}")
    finally:
        cursor.close()
        conn.close()

@router.delete("/meetings/{meeting_id}")
def delete_meeting(meeting_id: int):
    """刪除單場會議與其對應音訊檔。"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT audio_file_path FROM meetings WHERE id = %s", (meeting_id,))
        row = cursor.fetchone()
        if row and row['audio_file_path'] and os.path.exists(row['audio_file_path']):
            os.remove(row['audio_file_path'])
            
        cursor.execute("DELETE FROM meetings WHERE id = %s", (meeting_id,))
        conn.commit()
        return {"message": "會議紀錄刪除成功"}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()

# 🚀 聊天機器人路由（修復縮排與對齊）
@router.post("/meetings/{meeting_id}/chat")
def ask_meeting_bot(meeting_id: int, request: ChatRequest):
    """針對已儲存的會議內容回答使用者問題。

    端點會把逐字稿、摘要與圖片分析結果交給 RAG 服務，讓回答能引用該場會議
    的上下文，而不是只依賴一般語言模型知識。
    """
    conn = get_db_connection()
    ensure_image_analysis_column(conn)
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT transcript_text, image_analysis_text, summary_text FROM meetings WHERE id = %s", (meeting_id,))
        meeting = cursor.fetchone()
        if not meeting:
            raise HTTPException(status_code=404, detail="找不到此會議")

        transcript = meeting.get("transcript_text", "")
        image_analysis = meeting.get("image_analysis_text", "") or extract_image_analysis_from_transcript(transcript)
        summary = meeting.get("summary_text", "")

        if not transcript and not image_analysis:
            return {"answer": "這場會議目前沒有逐字稿或圖片分析紀錄，無法回答問題喔！"}

        answer = chat_with_meeting_rag(request.question, transcript, summary, image_analysis)
        return {"answer": answer}
    finally:
        cursor.close()
        conn.close()
