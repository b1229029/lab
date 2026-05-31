"""Google Calendar 整合服務。

摘要完成後，前端可以把 AI 建議的下次會議議程與時間送到後端；本檔負責
使用 OAuth 憑證建立 Google Calendar 事件，並寄送邀請給指定與會者。
"""

import os
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']

def create_google_calendar_event(topic, description, start_time_str, attendee_emails):
    """建立一個一小時的 Google Calendar 事件並回傳事件連結。

    token.json 儲存使用者授權結果；credentials.json 是 Google Cloud 下載
    的 OAuth client 設定。若 token 過期會自動 refresh，若尚未授權則啟動
    本機瀏覽器 OAuth 流程。
    """
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'): raise FileNotFoundError("找不到 credentials.json")
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token: token.write(creds.to_json())

    service = build('calendar', 'v3', credentials=creds)
    # 前端傳入 datetime-local 字串，這裡轉為 Asia/Taipei 時區的一小時會議。
    start_dt = datetime.datetime.fromisoformat(start_time_str)
    end_dt = start_dt + datetime.timedelta(hours=1)
    attendees = [{'email': email.strip()} for email in attendee_emails if email.strip()]

    event_body = {
        'summary': f"【跟進會議】{topic}", 'location': '線上會議室', 'description': description,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Taipei'},
        'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Taipei'},
        'attendees': attendees,
    }
    event = service.events().insert(calendarId='primary', body=event_body, sendUpdates='all').execute()
    return event.get('htmlLink')
