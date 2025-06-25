from flask import Flask, request, jsonify, render_template, Response
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image
import pytesseract
import gspread
from google.oauth2.service_account import Credentials
import re
import openai
import json

# === LOAD ENV ===
load_dotenv()
app = Flask(__name__)

# === ENV & CONFIG ===
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME_USERS = os.getenv("SHEET_NAME_USERS", "Users")
SHEET_NAME_LOGS = os.getenv("SHEET_NAME_LOGS", "Logs")
LIFF_ID = os.getenv("LIFF_ID")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:5000")

openai.api_key = OPENAI_API_KEY

# === GOOGLE SHEETS SETUP ===
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds_dict = {
    "type": os.getenv("GOOGLE_TYPE"),
    "project_id": os.getenv("GOOGLE_PROJECT_ID"),
    "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
    "auth_uri": os.getenv("GOOGLE_AUTH_URI"),
    "token_uri": os.getenv("GOOGLE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL")
}
creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
client = gspread.authorize(creds)
users_sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
logs_sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === UTILITIES ===
def send_line_message(reply_token, text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    body = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=body)

def is_thai_text(text):
    return bool(re.search(r'[\u0E00-\u0E7F]', text))

def find_or_create_user(user_id):
    users = users_sheet.get_all_records()
    for idx, user in enumerate(users):
        if user["user_id"] == user_id:
            return idx + 2
    users_sheet.append_row([user_id, 5, 0, 0, ""])
    return len(users) + 2

# === AI หมอดูไทย ===
def get_fortune(message):
    prompt = f"""คุณคือหมอดูไทยโบราณ ผู้มีญาณหยั่งรู้ พูดจาเคร่งขรึม สุภาพ ตอบคำถามเรื่องดวงชะตา ความรัก การเงิน และความฝัน\n\nผู้ใช้ถาม: \"{message}\"\nคำตอบของหมอดู:"""
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return response["choices"][0]["message"]["content"]

# === ROUTES ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    for event in data["events"]:
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]

        if event["type"] != "message":
            send_line_message(reply_token, "ระบบรองรับเฉพาะข้อความเท่านั้น 📩")
            return "ok"

        msg_type = event["message"]["type"]
        if msg_type != "text":
            send_line_message(reply_token, "ระบบรองรับเฉพาะข้อความเท่านั้น 🛑")
            return "ok"

        text = event["message"]["text"]
        if not is_thai_text(text):
            send_line_message(reply_token, "ระบบรองรับเฉพาะข้อความภาษาไทยเท่านั้น 🇹🇭")
            return "ok"

        row = find_or_create_user(user_id)
        values = users_sheet.row_values(row)
        quota = int(values[1])
        used = int(values[2])

        if quota <= 0:
            share_url = f"{PUBLIC_URL}/liff-share?referrer={user_id}"
            send_line_message(reply_token, f"คุณใช้สิทธิ์ครบแล้ว 🎯\nแชร์ลิงก์นี้เพื่อรับสิทธิ์ฟรี:\n{share_url}")
            return "ok"

        send_line_message(reply_token, "🧘‍♀️ หมอดูกำลังทำนาย รอสักครู่...")

        answer = get_fortune(text)

        requests.post("https://api.line.me/v2/bot/message/push", headers={
            "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }, json={
            "to": user_id,
            "messages": [{"type": "text", "text": answer}]
        })

        users_sheet.update_cell(row, 2, quota - 1)
        users_sheet.update_cell(row, 3, used + 1)
        logs_sheet.append_row([datetime.now().isoformat(), user_id, text, answer])

    return "ok"

@app.route("/liff-share")
def liff_share():
    referrer = request.args.get("referrer", "")
    return render_template("liff_share.html", liff_id=LIFF_ID, public_url=PUBLIC_URL, referrer=referrer)

@app.route("/shared")
def shared():
    user_id = request.args.get("user_id")
    referrer = request.args.get("referrer")

    if not user_id or not referrer or user_id == referrer:
        return "Invalid or duplicate share"

    users = users_sheet.get_all_records()
    user_row = find_or_create_user(user_id)
    ref_row = find_or_create_user(referrer)

    shared_from = users_sheet.row_values(user_row)[4]
    if referrer in shared_from.split(","):
        return "คุณได้รับสิทธิ์จากลิงก์นี้แล้ว"

    ref_quota = int(users_sheet.row_values(ref_row)[1])
    ref_shared = int(users_sheet.row_values(ref_row)[3])
    users_sheet.update_cell(ref_row, 2, ref_quota + 1)
    users_sheet.update_cell(ref_row, 4, ref_shared + 1)

    new_from = shared_from + "," + referrer if shared_from else referrer
    users_sheet.update_cell(user_row, 5, new_from)

    return "✅ ขอบคุณสำหรับการแชร์! ได้รับสิทธิ์เรียบร้อยแล้ว"

@app.route("/usage-summary")
def usage_summary():
    user_id = request.args.get("user_id")
    if not user_id:
        return "Missing user_id"

    rows = users_sheet.get_all_records()
    match = next((row for row in rows if row.get("user_id") == user_id), None)
    if not match:
        return "ไม่พบข้อมูลผู้ใช้นี้"

    return render_template("usage_summary.html",
                           user_id=user_id,
                           quota=match.get("quota", 0),
                           used=match.get("used", 0),
                           shared=match.get("shared", 0))

if __name__ == "__main__":
    app.run(debug=True)

