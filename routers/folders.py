from fastapi import APIRouter, HTTPException
import mysql.connector
import os
from database import get_db_connection
from schemas import FolderCreate

router = APIRouter(tags=["資料夾管理"])

@router.post("/folders")
def create_folder(request: FolderCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO folders (user_id, name) VALUES (%s, %s)", (request.user_id, request.name))
        conn.commit()
        return {"message": "資料夾建立成功！", "folder_id": cursor.lastrowid}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()

@router.get("/folders/{user_id}")
def get_user_folders(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM folders WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
        return {"folders": cursor.fetchall()}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()

@router.delete("/folders/{folder_id}")
def delete_folder(folder_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT audio_file_path FROM meetings WHERE folder_id = %s", (folder_id,))
        for row in cursor.fetchall():
            if row['audio_file_path'] and os.path.exists(row['audio_file_path']):
                os.remove(row['audio_file_path'])
        
        cursor.execute("DELETE FROM folders WHERE id = %s", (folder_id,))
        conn.commit()
        return {"message": "資料夾及內部紀錄刪除成功"}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()