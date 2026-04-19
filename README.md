***
# 「咪挺」– 你的會議紀錄助手
# 會議記錄即時專注系統 (Meeting Notes Real-time Focus System)

本專題旨在利用 AI 技術與即時音訊處理，解決會議中資訊零散、難以事後高效回溯的痛點，建立一個「錄音、總結、視覺化」一體化的解決方案。

## 📖 主題說明 (Project Overview)
在現代的商務與學術環境中，會議往往伴隨著龐大的資訊量。傳統的筆記方式難以兼顧「即時參與」與「完整記錄」。本系統開發了一套整合性的工具，讓使用者在錄製會議音訊的同時，系統能同步進行重點偵測，並在會後自動生成具備結構化、可互動的會議資產，讓使用者將精力專注於會議討論本身。

## ✨ 作品特色 (Product Features)
* **即時錄音與精準標記**：透過 Web Audio API 實現穩定錄音，並能在錄音過程中記錄關鍵時刻的時間點。
* **AI 智慧總結與萃取**：結合大語言模型 (LLM)，自動將冗長的會議轉譯內容精簡為條理清晰的重點大綱。
* **時間戳記互動心智圖**：**本系統核心亮點**。系統將會議重點轉化為心智圖，各節點與音訊時間軸連結。使用者點擊心智圖節點，播放器即可直接跳轉至對應音訊片段，實現「點哪裡、聽哪裡」。
* **專案化管理介面**：提供直覺的 Dashboard，方便使用者分類、儲存與檢索過往的會議記錄與心智圖檔案。

## 🏗️ 架構說明 (System Architecture)

### 1. 技術棧與組件
* **前端 (Frontend)**：HTML5, 原生 JavaScript (`audio_manager.js`, `record.js`, `ui_manager.js`)，透過 XAMPP 部署。
* **後端 (Backend)**：Python / FastAPI (`main.py`, `routers/`, `services/`)
* **資料庫 (Database)**：透過 `database.py` 與 `schemas.py` 進行資料模型定義與持久化

### 2. 專案目錄結構
```text
.
├── main.py                 # 後端 API 程式進入點
├── listener.py             # 監聽與背景任務處理
├── database.py             # 資料庫連線與配置
├── schemas.py              # 資料驗證與結構定義 (Pydantic models)
│
├── routers/                # API 路由模組
│   ├── auth.py             # 登入與身份驗證
│   ├── folders.py          # 專案資料夾管理
│   └── meetings.py         # 會議記錄存取
│
├── services/               # 核心商業邏輯與外部 API 串接
│   ├── ai_service.py       # AI 總結與文本分析
│   ├── audio_service.py    # 音訊格式處理與轉換
│   └── calendar_service.py # 日曆整合服務
│
├── uploads/                # 音訊檔案上傳與處理暫存目錄
│
├── index.html              # 系統首頁
├── login.html              # 使用者登入介面
├── dashboard.html          # 儀表板 (專案與會議列表)
├── view.html               # 會議記錄檢視與心智圖同步介面
│
├── audio_manager.js        # 前端音訊播放與時間跳轉控制
├── record.js               # 前端錄音功能實作
└── ui_manager.js           # 心智圖渲染與 UI 互動管理

--- 以下為本地端執行必備檔案 (未追蹤於 GitHub) ---
├── credentials.json        # 外部服務 API 憑證 
├── token.json              # 授權 Token 紀錄
├── ffmpeg.exe              # 音訊轉檔與處理引擎
└── ffprobe.exe             # 音訊資訊分析工具
```

## 🎯 預期成果 (Expected Results)
* **大幅提升回溯效率**：使用者不再需要完整重聽錄音，節省 尋找資訊的時間。
* **結構化知識沉澱**：將原本零散的口頭討論自動轉化為可搜尋、可視化的結構化文件。
* **強化記憶連結**：透過視覺化的心智圖結構與音訊直接掛鉤，強化使用者對會議邏輯的理解。

## 💻 系統需求與安裝 (System Requirements & Setup)

### 軟硬體環境
* **作業系統**：Windows 10/11
* **網頁伺服器**：XAMPP (Apache)
* **開發環境**：Python 3.8+
* **瀏覽器**：建議使用 Google Chrome / Edge (需開啟麥克風權限)
* **硬體**：需具備音訊輸入設備 (麥克風)

### 1. 環境設定 (首次執行)
請將專案資料夾放置於 XAMPP 的 `htdocs` 目錄下（路徑應為 `C:\xampp\htdocs\whisper.0`），並開啟 Windows PowerShell 建立與啟動虛擬環境：
```powershell
cd C:\xampp\htdocs\whisper.0
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```
*(註：確保您的本地端已放置必要的憑證檔與 FFmpeg 工具於專案根目錄。)*

### 2. 🚀 啟動系統 (Running Locally)
每次開發或測試時，請依序執行以下步驟：

**Step 1: 啟動背景監聽程式**
開啟第一個 PowerShell 視窗：
```powershell
cd C:\xampp\htdocs\whisper.0
.\venv\Scripts\activate
python listener.py
```

**Step 2: 啟動後端 API 伺服器**
開啟第二個 PowerShell 視窗：
```powershell
cd C:\xampp\htdocs\whisper.0
uvicorn main:app --reload
```
*(若全域未安裝 uvicorn，請在此視窗也先執行 `.\venv\Scripts\activate`)*

**Step 3: 開啟前端網頁**
1. 確保您的 XAMPP 控制面板已開啟 **Apache** 和 **MySQL** 服務。
2. 開啟瀏覽器，輸入您的區域網路 IP 與專案路徑即可開始使用。

---
```
