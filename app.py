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
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")

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
users_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
logs_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === BASIC AUTH ===
def require_basic_auth():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
        return Response("กรุณาเข้าสู่ระบบ", 401, {"WWW-Authenticate": "Basic realm='Admin Access'"})

# === LINE FUNCTIONS ===
def send_line_message(reply_token, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=body)

def push_line_message(user_id, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)

# === ตรวจสอบภาษาไทย ===
def is_thai(text):
    return bool(re.search(r'[\u0E00-\u0E7F]', text))

# === AI หมอดูไทย ===
def get_fortune(message):
    prompt = f"""คุณคือหมอดูไทยโบราณ พูดจาสุภาพ ตอบคำถามเรื่องดวง ความรัก การเงิน หรือความฝัน\n\nถาม: "{message}"\nตอบ:"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        return f"ขออภัย ระบบหมอดู AI ขัดข้อง: {str(e)}"

# === Flex Message เชิญเพิ่มเพื่อน ===
def send_invite_friend_flex(user_id, count):
    flex_message = {
        "type": "flex",
        "altText": f"🎉 ใช้งานครบ {count} ครั้ง! แชร์บอทนี้ให้เพื่อนเลย",
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
                "spacing": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": f"🎉 คุณใช้ครบ {count} ครั้งแล้ว!",
                        "weight": "bold",
                        "size": "xl",
                        "wrap": True
                    },
                    {
                        "type": "text",
                        "text": "แชร์บอทนี้ให้เพื่อน แล้วรับสิทธิ์ใช้งานฟรีเพิ่ม 🎁",
                        "wrap": True,
                        "size": "md",
                        "color": "#666666"
                    }
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
                        "color": "#1DB446",
                        "action": {
                            "type": "uri",
                            "label": "📎 แชร์ให้เพื่อน",
                            "uri": "https://line.me/R/nv/addFriends?alias=duangjitai"
                        }
                    }
                ]
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json={
        "to": user_id,
        "messages": [flex_message]
    })

# === LOGGING และเช็กทุก 5 ครั้ง ===
def log_usage(user_id, action, detail):
    now = datetime.now().isoformat()
    try:
        logs_sheet.append_row([now, user_id, action, detail])
        logs = logs_sheet.get_all_records()
        count = sum(1 for row in logs if row["user_id"] == user_id and row["action"] == "ใช้งานฟรี")
        if count > 0 and count % 5 == 0:
            send_invite_friend_flex(user_id, count)
    except Exception as e:
        print("Log error:", e)

# === ทำนายและตอบกลับแบบ background ===
def handle_fortune(user_id, message_text):
    reply = get_fortune(message_text)
    push_line_message(user_id, reply)
    log_usage(user_id, "ใช้งานฟรี", message_text)

# === ROUTES ===
@app.route("/")
def home():
    return "ดวงจิต AI พร้อมใช้งานฟรีแล้ว 🎉"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    for event in data.get("events", []):
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]

        if event["type"] != "message" or event["message"]["type"] != "text":
            send_line_message(reply_token, "❌ ขออภัย ระบบรองรับเฉพาะข้อความเท่านั้น")
            return jsonify({"status": "ignored_non_text"})

        message_text = event["message"]["text"].strip()
        if not is_thai(message_text):
            send_line_message(reply_token, "📌 ระบบรองรับเฉพาะข้อความภาษาไทยเท่านั้น")
            return jsonify({"status": "ignored_non_thai"})

        send_line_message(reply_token, "🧘‍♀️ หมอดูกำลังทำนาย รอสักครู่...")
        threading.Thread(target=handle_fortune, args=(user_id, message_text)).start()

    return jsonify({"status": "ok"})

@app.route("/admin")
def admin_dashboard():
    auth = require_basic_auth()
    if auth: return auth
    records = users_sheet.get_all_records()
    return render_template("admin_dashboard.html", users=records)

@app.route("/test-sheet")
def test_sheet():
    try:
        data = users_sheet.get_all_records()
        return jsonify({"status": "success", "data": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# === EXPORT FOR RENDER ===
application = app

