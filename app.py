from flask import Flask, request, jsonify, render_template, Response
import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import openai
import threading
import re
import json
from bs4 import BeautifulSoup

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

def send_flex_lucky_numbers(user_id, lucky_data):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    flex = build_lucky_flex(lucky_data)
    body = {"to": user_id, "messages": [json.loads(flex)]}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)

# === AI หมอดูไทย ===
def get_fortune(message):
    prompt = f"""คุณคือหมอดูไทยโบราณ พูดจาสุภาพ ตอบคำถามเรื่องดวง ความรัก การเงิน หรือความฝัน\n\nถาม: \"{message}\"\nตอบ:"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        return f"ขออภัย ระบบหมอดู AI ขัดข้อง: {str(e)}"

# === LOGGING (รันใน thread แยก) ===
def log_usage(user_id, action, detail):
    now = datetime.now().isoformat()
    try:
        logs_sheet.append_row([now, user_id, action, detail])
    except Exception as e:
        print("Log error:", e)

# === ฟังก์ชันตรวจสอบข้อความภาษาไทย + ตัวเลขเท่านั้น ===
def is_valid_thai_text(text):
    pattern = r'^[\u0E00-\u0E7F0-9\s\.\,\?\!]+$'
    return bool(re.match(pattern, text))

# === FLEX LUCKY ===
def build_lucky_flex(lucky_data):
    bubbles = []
    for name, info in lucky_data.items():
        bubble = {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {"type": "text", "text": f"🔮 {name}", "weight": "bold", "size": "md"},
                    {"type": "text", "text": f"📅 งวด {info['date']}", "size": "sm", "color": "#AAAAAA"},
                    {"type": "text", "text": f"✨ เลข 2 ตัว: {', '.join(info.get('two', []))}", "wrap": True},
                    {"type": "text", "text": f"🔢 เลข 3 ตัว: {', '.join(info.get('three', []))}", "wrap": True}
                ]
            }
        }
        if 'chup' in info:
            bubble["body"]["contents"].append(
                {"type": "text", "text": f"🔥 เลขธูป: {', '.join(info['chup'])}", "wrap": True, "color": "#FF3333"}
            )
        bubbles.append(bubble)

    flex_message = {
        "type": "flex",
        "altText": "📌 เลขเด็ดงวดนี้จากเจ้าแม่ชื่อดัง",
        "contents": {"type": "carousel", "contents": bubbles}
    }
    return json.dumps(flex_message, ensure_ascii=False)

# === FETCH LUCKY ===
cache = {"data": None, "last_update": datetime.min}

def fetch_lucky_auto():
    now = datetime.now()
    if cache["data"] and now - cache["last_update"] < timedelta(hours=6):
        return cache["data"]

    try:
        r = requests.get("https://www.dailynews.co.th/news/2533714/")
        soup = BeautifulSoup(r.text, "html.parser")
        content = soup.get_text()
        data = {}

        m1 = re.search(r'แม่น้ำหนึ่ง.*?เลขสองตัว\s*:\s*([\d\-\s]+).*?เลขสามตัว\s*:\s*([\d\-\s]+)', content, re.S)
        n1 = re.search(r'เจ๊นุ๊ก.*?เลขเด่น\s*(\d+).*?สามตัว\s*([\d\-\s,]+).*?สองตัว\s*([\d\-\s,]+)', content, re.S)
        f1 = re.search(r'เจ๊ฟองเบียร์.*?เด่น\s*([\d\-]+).*?สองตัว.*?([\d\-\s,]+).*?สามตัว.*?([\d\-\s,]+)', content, re.S)

        if m1:
            data['แม่น้ำหนึ่ง'] = {
                'date': now.strftime("%d %B %Y"),
                'two': m1.group(1).strip().split(),
                'three': m1.group(2).strip().split()
            }
        if n1:
            data['เจ๊นุ๊ก'] = {
                'date': now.strftime("%d %B %Y"),
                'lead': [n1.group(1)],
                'three': n1.group(2).split(),
                'two': n1.group(3).split()
            }
        if f1:
            data['เจ๊ฟองเบียร์'] = {
                'date': now.strftime("%d %B %Y"),
                'lead': [f1.group(1)],
                'two': f1.group(2).split(),
                'three': f1.group(3).split()
            }

        cache.update({"data": data, "last_update": now})
        return data

    except Exception as e:
        return cache["data"] or {}

# === ROUTES ===
@app.route("/")
def home():
    return "ดวงจิต AI พร้อมใช้งานฟรีแล้ว 🎉"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    for event in data.get("events", []):
        if event["type"] != "message":
            continue

        message_type = event["message"]["type"]
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]

        if message_type != "text":
            send_line_message(reply_token, "📌 กรุณาพิมพ์ข้อความเป็นภาษาไทยเท่านั้น เช่น ถามเรื่องดวง ความฝัน หรือโชคลาภ")
            continue

        message_text = event["message"]["text"].strip()

        if not is_valid_thai_text(message_text):
            send_line_message(reply_token, "📌 โปรดใช้เฉพาะข้อความภาษาไทย หรือเลขเท่านั้น เช่น \"ฝันเห็นงู\" หรือ \"ดวงการเงินวันนี้\"")
            continue

        if message_text == "เลขเด็ดงวดนี้":
            lucky_data = fetch_lucky_auto()
            if not lucky_data:
                send_line_message(reply_token, "❌ ขออภัย ไม่สามารถดึงเลขเด็ดงวดนี้ได้ในขณะนี้")
            else:
                send_line_message(reply_token, "📥 กำลังดึงเลขเด็ดล่าสุด...")
                send_flex_lucky_numbers(user_id, lucky_data)
            continue

        elif re.match(r'^\d{2,3}$', message_text):
            lucky_data = fetch_lucky_auto()
            num = message_text
            hit = []
            for name, info in lucky_data.items():
                if num in info.get("two", []) or num in info.get("three", []) or num in info.get("chup", []):
                    hit.append(f"✅ {name} มีเลขนี้!")
            if hit:
                send_line_message(reply_token, f"🔍 ตรวจเลข {num} พบว่า:\n" + "\n".join(hit))
            else:
                send_line_message(reply_token, f"❌ ไม่พบเลข {num} ในเลขเด็ดงวดนี้")
            continue

        send_line_message(reply_token, "🧘‍♀️ หมอดูกำลังทำนาย รอสักครู่...")

        def reply_later():
            reply = get_fortune(message_text)
            push_line_message(user_id, reply)
            log_usage(user_id, "ใช้งานฟรี", message_text)

        threading.Thread(target=reply_later).start()

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

