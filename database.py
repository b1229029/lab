"""MySQL 連線與資料表初始化工具。

後端所有 router 都透過本檔取得資料庫連線，並在服務啟動時建立 users、
folders、meetings 三張核心資料表。這裡也保留向後相容的欄位補齊邏輯，
讓舊資料庫升級後仍能儲存圖片分析文字。
"""

import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    # 本機開發用連線設定；正式部署時建議改由環境變數或密鑰管理服務提供。
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'whisper_meetings'
}

def get_db_connection():
    """建立並回傳一個 MySQL 連線。

    回傳值可能是有效連線，也可能在連線失敗時為 None；呼叫端需要在使用
    cursor 前確認連線存在，避免資料庫未啟動時造成未處理例外。
    """
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"❌ 資料庫連線失敗: {e}")
        return None

def ensure_image_analysis_column(conn):
    """確認 meetings 資料表存在 image_analysis_text 欄位。

    這個欄位是後續加入的功能，用來保存圖片辨識結果。若使用者已經有舊版
    資料庫，本函式會自動 ALTER TABLE 補欄位，避免手動 migration。
    """
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'meetings'
              AND COLUMN_NAME = 'image_analysis_text'
        """)
        if cursor.fetchone()[0] == 0:
            cursor.execute("ALTER TABLE meetings ADD COLUMN image_analysis_text LONGTEXT DEFAULT NULL AFTER transcript_text")
            conn.commit()
    finally:
        cursor.close()

def create_tables():
    """建立專案需要的基本資料表並補齊新版欄位。

    users 保存帳號資料，folders 保存使用者的會議資料夾，meetings 保存
    單場會議的逐字稿、摘要、心智圖與音訊檔路徑。外鍵皆使用 cascade delete，
    讓刪除使用者或資料夾時可同步清掉下層資料。
    """
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cursor = conn.cursor()
        
        # 1. 建立會員表 (users)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                reset_token VARCHAR(255) DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 2. 建立資料夾表 (folders)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)

        # 3. 建立會議表 (meetings) - 包含音檔路徑
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meetings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                folder_id INT NOT NULL,
                title VARCHAR(255) NOT NULL,
                transcript_text LONGTEXT DEFAULT NULL,
                image_analysis_text LONGTEXT DEFAULT NULL,
                summary_text LONGTEXT DEFAULT NULL,
                mindmap_data LONGTEXT DEFAULT NULL,
                audio_file_path VARCHAR(500) DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE
            )
        """)

        conn.commit()
        ensure_image_analysis_column(conn)
        print("✅ 資料庫與表格初始化成功！")
        
    except Error as e:
        print(f"❌ 建立表格時發生錯誤: {e}")
    finally:
        if conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == '__main__':
    create_tables()
