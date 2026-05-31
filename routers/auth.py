"""帳號註冊與登入 API。

此 router 提供前端 login.html 呼叫的 /register 與 /login 端點。密碼不以
明文保存，而是透過 passlib 的 pbkdf2_sha256 產生雜湊後寫入資料庫。
"""

from fastapi import APIRouter, HTTPException
import mysql.connector
from passlib.context import CryptContext
from database import get_db_connection
from schemas import RegisterRequest, LoginRequest

# 建立 Router，並加上標籤方便未來閱讀 API 文件
router = APIRouter(tags=["會員驗證"])
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

@router.post("/register")
def register_user(request: RegisterRequest):
    """建立新使用者帳號。

    流程：
    1. 檢查 email 是否已存在。
    2. 將密碼雜湊後寫入 users 表。
    3. 回傳新使用者 id，供前端確認註冊成功。
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (request.email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="這個 Email 已經被註冊過了！")
        
        hashed_password = pwd_context.hash(request.password)
        cursor.execute("INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)", 
                       (request.username, request.email, hashed_password))
        conn.commit()
        return {"message": "註冊成功！", "user_id": cursor.lastrowid}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()

@router.post("/login")
def login_user(request: LoginRequest):
    """驗證使用者登入資料並回傳前端需要的基本身分資訊。

    登入成功時只回傳 id、username、email，不回傳 password_hash，避免敏感
    資料被存到瀏覽器 localStorage。
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM users WHERE email = %s", (request.email,))
        user = cursor.fetchone()
        if not user or not pwd_context.verify(request.password, user['password_hash']):
            raise HTTPException(status_code=401, detail="Email 或密碼錯誤！")
        return {"message": "登入成功！", "user": {"id": user["id"], "username": user["username"], "email": user["email"]}}
    except mysql.connector.Error as e:
        raise HTTPException(status_code=500, detail=f"資料庫錯誤: {e}")
    finally:
        cursor.close()
        conn.close()
