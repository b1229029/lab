import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# 👇 引入我們剛剛拆分好的 Routers
from routers import auth, folders, meetings

app = FastAPI(title="Whisper 會議助手 API")

# 建立儲存音檔的資料夾
os.makedirs("uploads", exist_ok=True)

# 讓前端可以透過 URL 直接讀取 uploads 資料夾內的檔案
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# 設定 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 👇 將外部的 API 路由「掛載」到主程式
app.include_router(auth.router)
app.include_router(folders.router)
app.include_router(meetings.router)