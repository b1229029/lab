"""API 請求資料結構。

Pydantic model 會替 FastAPI 驗證前端傳入的 JSON 欄位型別，也讓 router
函式能用明確的屬性讀取 request body，減少手動解析 dict 的錯誤。
"""

from pydantic import BaseModel
from typing import Optional

class RegisterRequest(BaseModel):
    """註冊帳號時前端必須提供的欄位。"""
    username: str
    email: str
    password: str

class LoginRequest(BaseModel):
    """登入時使用 email 與密碼驗證身分。"""
    email: str
    password: str

class FolderCreate(BaseModel):
    """建立資料夾時要知道資料夾屬於哪位使用者。"""
    user_id: int
    name: str

class MeetingCreate(BaseModel):
    """建立會議時先記錄所屬資料夾與會議標題。"""
    folder_id: int
    title: str

class MeetingUpdate(BaseModel):
    """會議結束後儲存 AI 產物；欄位皆可選以支援部分更新。"""
    transcript_text: Optional[str] = None
    image_analysis_text: Optional[str] = None
    summary_text: Optional[str] = None
    mindmap_data: Optional[str] = None
