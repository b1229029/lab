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