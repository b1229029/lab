"""資料夾管理 API。

資料夾是 dashboard.html 的第一層組織單位，用來把不同主題或課程的會議
分開管理。刪除資料夾時也會清掉該資料夾底下會議的音訊檔案。
"""

from fastapi import APIRouter, HTTPException
import mysql.connector
import os
from database import get_db_connection
from schemas import FolderCreate

router = APIRouter(tags=["資料夾管理"])

@router.post("/folders")
def create_folder(request: FolderCreate):
    """替指定使用者建立一個新的會議資料夾。"""
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
    """依使用者 id 取得資料夾清單，最新建立的資料夾排在前面。"""
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
    """刪除資料夾與其下所有會議資料。

    資料庫會透過外鍵 cascade 刪除 meetings；這裡額外先刪除音訊實體檔，
    避免 uploads 目錄累積孤兒檔案。
    """
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
