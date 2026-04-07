# schemas.py
from pydantic import BaseModel
from typing import Optional

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class FolderCreate(BaseModel):
    user_id: int
    name: str

class MeetingCreate(BaseModel):
    folder_id: int
    title: str

class MeetingUpdate(BaseModel):
    transcript_text: Optional[str] = None
    summary_text: Optional[str] = None
    mindmap_data: Optional[str] = None