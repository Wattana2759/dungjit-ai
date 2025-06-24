from flask import Flask, request, jsonify, render_template, Response
import os, requests, re
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image
import pytesseract
import gspread
from google.oauth2.service_account import Credentials
import openai

# === LOAD ENV ===
load_dotenv()
app = Flask(__name__)

# === ENV CONFIG ===
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME_USERS = os.getenv("SHEET_NAME_USERS")
SHEET_NAME_LOGS = os.getenv("SHEET_NAME_LOGS")
LIFF_ID = os.getenv("LIFF_ID")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:5000")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")
openai.api_key = OPENAI_API_KEY

# === GOOGLE SHEETS ===
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
users_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
logs_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === USER MANAGEMENT ===
def get_user(user_id):
    records = users_sheet.get_all_records()
    for i, row in enumerate(records):
        if row["user_id"] == user_id:
            return row, i + 2
    return None, None

def update_user(user_id, usage=None, quota=None):
    _, row = get_user(user_id)
    if row:
        if usage is not None: users_sheet.update_cell(row, 3, usage)
        if quota is not None: users_sheet.update_cell(row, 4, quota)

def add_or_update_user(user_id, name, added_quota, ref):
    user, row = get_user(user_id)
    now = datetime.now().isoformat()
    if user:
        new_quota = int(user["paid_quota"]) + added_quota
        users_sheet.update(f"C{row}:F{row}", [[user["usage"], new_quota, ref, now]])
    else:
        users_sheet.append_row([user_id, name, 0, added_quota, ref, now])

# === LINE MESSAGES ===
def push_line_message(user_id, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    response = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)
    print("LINE Text Response:", response.status_code, response.text)

def send_invite_link(user_id):
    line_oa_id = "@duangjitai"
    share_url = f"https://line.me/R/oaMessage/{line_oa_id}/?{user_id}"
    flex = {
        "type": "flex",
        "altText": "🏱 ชวนเพื่อนรับสิทธิ์ฟรี",
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "🏱 ชวนเพื่อน รับสิทธิ์ฟรี 5 ครั้ง!", "weight": "bold", "size": "md", "wrap": True},
                    {"type": "text", "text": "แชร์ลิงก์นี้ให้เพื่อนเพิ่มเพื่อน แล้วคุณจะได้รับสิทธิ์ทันที!", "size": "sm", "wrap": True}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "action": {
                            "type": "uri",
                            "label": "📤 แชร์ลิงก์ให้เพื่อน",
                            "uri": share_url
                        }
                    }
                ]
            }
        }
    }
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"to": user_id, "messages": [flex]}
    response = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)
    print("LINE Flex Response:", response.status_code, response.text)

# === WEBHOOK ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    for event in data.get("events", []):
        event_type = event["type"]
        user_id = event["source"]["userId"]

        if event_type == "follow":
            referrer_id = request.args.get("ref", "")
            if referrer_id and referrer_id != user_id:
                ref_user, ref_row = get_user(referrer_id)
                if ref_user:
                    new_quota = int(ref_user["paid_quota"]) + 5
                    users_sheet.update_cell(ref_row, 4, new_quota)
                    push_line_message(referrer_id, "\ud83c\udf89 เพื่อนของคุณเข้าร่วมแล้ว! รับสิทธิ์เพิ่ม 5 ครั้ง ✅")
            add_or_update_user(user_id, "New User", 0, "ref")
            push_line_message(user_id, "ยินดีต้อนรับ! แชร์บอทให้เพื่อน แล้วคุณจะได้รับสิทธิ์ใช้ฟรี 5 ครั้ง")
            continue

        if event_type != "message" or event["message"]["type"] != "text":
            continue

        message_text = event["message"]["text"].strip()
        reply_token = event["replyToken"]
        user, _ = get_user(user_id)

        if not user or int(user["paid_quota"]) <= int(user["usage"]):
            push_line_message(user_id, "📌 คุณยังไม่มีสิทธิ์ใช้งาน")
            send_invite_link(user_id)
            continue

        reply = f"คุณถาม: {message_text}\nหมอตอบ: ยังไม่ได้เชื่อม AI จริง"
        push_line_message(user_id, reply)
        update_user(user_id, usage=int(user["usage"]) + 1)

    return jsonify({"status": "ok"})

application = app

