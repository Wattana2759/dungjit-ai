from flask import Flask, request, jsonify, render_template, Response
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import openai
import threading
import re

# === LOAD ENV ===
load_dotenv()
app = Flask(__name__)

# === ENV & CONFIG ===
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME_USERS = os.getenv("SHEET_NAME_USERS")
SHEET_NAME_LOGS = os.getenv("SHEET_NAME_LOGS")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:5000")

openai.api_key = OPENAI_API_KEY

# === GOOGLE SHEETS SETUP ===
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
logs_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === LINE MESSAGE ===
def send_line_message(reply_token, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=body)

def push_line_message(user_id, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)

# === ภาษาไทยเท่านั้น ===
def is_thai(text):
    return bool(re.search(r'[\u0E00-\u0E7F]', text))

# === หมอดู AI ===
def get_fortune(message):
    prompt = f"คุณคือหมอดูไทยโบราณที่ตอบเรื่องดวง ความรัก การเงิน ความฝัน อย่างสุภาพ\n\nถาม: {message}\nตอบ:"
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        return f"ขออภัย ระบบขัดข้อง: {str(e)}"

# === LOG และให้สิทธิ์เมื่อครบ 5 ครั้ง ===
def log_usage(user_id, action, detail):
    now = datetime.now().isoformat()
    logs_sheet.append_row([now, user_id, action, detail])

    logs = logs_sheet.get_all_records()
    count = sum(1 for row in logs if row["user_id"] == user_id and row["action"] == "ใช้งานฟรี")
    if count > 0 and count % 5 == 0:
        send_invite_friend_flex(user_id, count)

# === แชร์ Flex Message ===
def send_invite_friend_flex(user_id, count):
    flex_message = {
        "type": "flex",
        "altText": f"🎉 ครบ {count} ครั้ง! แชร์บอทนี้ให้เพื่อนเลย",
        "contents": {
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": "https://res.cloudinary.com/dwg28idpf/image/upload/v1750824745/ChatGPT_Image_25_%E0%B8%A1%E0%B8%B4.%E0%B8%A2._2568_11_10_18_mr9phf.png",
                "size": "full",
                "aspectRatio": "16:9",
                "aspectMode": "cover"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"คุณใช้ครบ {count} ครั้งแล้ว!", "weight": "bold", "size": "xl"},
                    {"type": "text", "text": "แชร์ให้เพื่อนแล้วรับสิทธิ์ใช้งานฟรีเพิ่ม 🎁", "size": "sm", "wrap": True}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "action": {
                            "type": "uri",
                            "label": "📎 แชร์ให้เพื่อน",
                            "uri": f"{PUBLIC_URL}/shared?referrer={user_id}"
                        }
                    }
                ]
            }
        }
    }

    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json={"to": user_id, "messages": [flex_message]})

# === ดำเนินการทำนายใน thread ===
def handle_fortune(user_id, message_text):
    reply = get_fortune(message_text)
    push_line_message(user_id, reply)
    log_usage(user_id, "ใช้งานฟรี", message_text)

# === แชร์ลิงก์สำเร็จ รับสิทธิ์ ===
@app.route("/shared")
def shared():
    referrer_id = request.args.get("referrer")
    if not referrer_id:
        return "ลิงก์ไม่ถูกต้อง"
    now = datetime.now().isoformat()
    logs_sheet.append_row([now, referrer_id, "ได้สิทธิ์จากการแชร์", "referral"])
    return "✅ ระบบรับทราบว่าคุณแชร์แล้ว! ได้รับสิทธิ์เพิ่ม 1 ครั้ง"

# === Webhook หลัก LINE ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    for event in data.get("events", []):
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]

        if event["type"] != "message" or event["message"]["type"] != "text":
            send_line_message(reply_token, "❌ รองรับเฉพาะข้อความภาษาไทยเท่านั้น")
            return jsonify({"status": "ignored"})

        message_text = event["message"]["text"].strip()
        if not is_thai(message_text):
            send_line_message(reply_token, "📌 กรุณาพิมพ์เป็นภาษาไทยเท่านั้น")
            return jsonify({"status": "non_thai"})

        send_line_message(reply_token, "🧘‍♀️ หมอดูกำลังทำนาย รอสักครู่...")
        threading.Thread(target=handle_fortune, args=(user_id, message_text)).start()

    return jsonify({"status": "ok"})

@app.route("/")
def home():
    return "Duangjit AI พร้อมใช้งาน"

application = app

