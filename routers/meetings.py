from fastapi import APIRouter, HTTPException, UploadFile, File
import mysql.connector
import os
import shutil
from database import get_db_connection
from schemas import MeetingCreate, MeetingUpdate

router = APIRouter(tags=["會議管理"])

@router.post("/meetings")
def create_meeting(request: MeetingCreate):
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
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM meetings WHERE id = %s", (meeting_id,))
        meeting = cursor.fetchone()
        if not meeting:
            raise HTTPException(status_code=404, detail="找不到這場會議")
        return meeting
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()

@router.put("/meetings/{meeting_id}")
def save_meeting_results(meeting_id: int, request: MeetingUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE meetings 
            SET transcript_text = %s, summary_text = %s, mindmap_data = %s
            WHERE id = %s
        """, (request.transcript_text, request.summary_text, request.mindmap_data, meeting_id))
        conn.commit()
        return {"message": "會議紀錄已成功儲存到資料庫！"}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()

@router.post("/meetings/{meeting_id}/upload_audio")
def upload_meeting_audio(meeting_id: int, file: UploadFile = File(...)):
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