# services/calendar_service.py
import os
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']

def create_google_calendar_event(topic, description, start_time_str, attendee_emails):
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