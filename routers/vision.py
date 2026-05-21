from fastapi import APIRouter, File, UploadFile, HTTPException
import base64
from openai import OpenAI

# 建立 Router，設定統一的前綴路徑
router = APIRouter(prefix="/vision", tags=["Vision圖片辨識"])

# API 設定
API_KEY = "sk-f884955258b0a4890c9aab6caab212c9c60a6424d4f1c775" # 建議未來改用環境變數 (os.getenv)
BASE_URL = "https://air.cgu.edu.tw/cgullmapi/v1"
MODEL = "gpt-5.4-mini"  # 🎯 這裡已經幫你修正為正確的模型名稱囉！

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

@router.post("/analyze")
async def analyze_image(file: UploadFile = File(...)):
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