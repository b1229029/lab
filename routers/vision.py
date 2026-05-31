"""圖片分析 API。

前端可上傳會議截圖、白板或投影片圖片，本 router 會把圖片轉成 base64
data URL 並交給支援 vision 的 OpenAI-compatible API 產生文字描述。
"""

from fastapi import APIRouter, File, UploadFile, HTTPException
import base64
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

# 建立 Router，設定統一的前綴路徑
router = APIRouter(prefix="/vision", tags=["Vision圖片辨識"])

# 讀取環境變數
API_KEY = os.getenv("VISION_API_KEY")
BASE_URL = os.getenv("BASE_URL")
MODEL = "gpt-5.4-mini"

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

@router.post("/analyze")
async def analyze_image(file: UploadFile = File(...)):
    """分析單張圖片並回傳模型描述。

    只接受 image/* MIME type，避免把非圖片檔送到 vision 模型。回傳的
    description 會被前端加入會議紀錄，後續摘要與 RAG 問答都能使用。
    """
    # 1. 檢查檔案格式是否為圖片
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="請上傳圖片檔案")

    try:
        # 2. 讀取前端上傳的圖片內容，並直接在記憶體中轉為 Base64 (不需要存檔)
        contents = await file.read()
        image_base64 = base64.b64encode(contents).decode("utf-8")
        
        # 取得圖片類型 (例如 image/png, image/jpeg)
        mime_type = file.content_type

        # 3. 呼叫模型 API
        response = client.responses.create(
            model=MODEL,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "請用繁體中文說明這張圖片的內容。"
                        },
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime_type};base64,{image_base64}"
                        }
                    ]
                }
            ],
            max_output_tokens=800,
        )

        # 4. 回傳辨識結果給前端
        return {
            "status": "success",
            "filename": file.filename,
            "description": response.output_text
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"圖片辨識失敗: {str(e)}")
