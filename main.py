"""FastAPI 應用程式入口。

本檔負責建立後端 API 服務、初始化資料表、開放上傳檔案的靜態路徑，
並把各功能模組的 router 掛載到同一個 FastAPI app。實際的商業邏輯
分散在 routers/ 與 services/ 內，main.py 只保留啟動與組裝責任。
"""

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# 👇 引入所有的 Routers (包含最新加入的 vision)
from routers import auth, folders, meetings, vision
from database import create_tables

app = FastAPI(title="Whisper 會議助手 API")

@app.on_event("startup")
def startup_event():
    """伺服器啟動時建立或補齊資料庫表格。

    FastAPI 在啟動事件觸發後才開始接收請求，因此這裡適合做一次性的
    資料庫 schema 檢查，避免第一個使用者請求才遇到資料表不存在。
    """
    create_tables()

# 建立儲存音檔的資料夾
os.makedirs("uploads", exist_ok=True)

# 讓前端可以透過 URL 直接讀取 uploads 資料夾內的檔案
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# 設定 CORS (允許前端跨域請求)
app.add_middleware(
    CORSMiddleware,
    # 前端頁面以本機靜態 HTML 方式載入時，來源可能不是 API 網域；
    # 目前畢業專題環境採全開 CORS，方便前後端在不同 port 測試。
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 👇 將外部的 API 路由「掛載」到主程式
app.include_router(auth.router)
app.include_router(folders.router)
app.include_router(meetings.router)
app.include_router(vision.router) # 👉 新增的圖片辨識路由
