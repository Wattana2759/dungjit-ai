import re
import os
from datetime import datetime
import gspread
import requests
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# LINE
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")

# Google Sheet Auth
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
service_account_info = {
    "type": os.getenv("GOOGLE_TYPE"),
    "project_id": os.getenv("GOOGLE_PROJECT_ID"),
    "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace('\\n', '\n'),
    "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
    "auth_uri": os.getenv("GOOGLE_AUTH_URI"),
    "token_uri": os.getenv("GOOGLE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL"),
}
creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
gc = gspread.authorize(creds)
users_sheet = gc.open_by_key(os.getenv("GOOGLE_SHEET_ID")).worksheet(os.getenv("SHEET_NAME_USERS"))
logs_sheet = gc.open_by_key(os.getenv("GOOGLE_SHEET_ID")).worksheet(os.getenv("SHEET_NAME_LOGS"))

def extract_payment_info(text):
    name = re.search(r"(ชื่อ[^\n\r]+)", text)
    amount = re.search(r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\\s*(บาท|฿)?", text)
    return {
        "amount": amount.group(1).replace(",", "") if amount else None,
        "name": name.group(1).strip() if name else None
    }

def add_or_update_user(user_id, name, added_quota, slip_file):
    records = users_sheet.get_all_records()
    row = None
    for i, user in enumerate(records):
        if user["user_id"] == user_id:
            row = i + 2
            break
    now = datetime.now().isoformat()
    if row:
        current = records[i]
        new_quota = int(current["paid_quota"]) + added_quota
        users_sheet.update(f"C{row}:F{row}", [[current["usage"], new_quota, slip_file, now]])
    else:
        users_sheet.append_row([user_id, name, 0, added_quota, slip_file, now])

def push_line_message(user_id, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)

def log_usage(user_id, action, detail):
    now = datetime.now().isoformat()
    logs_sheet.append_row([now, user_id, action, detail])
