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
import time

# === LOAD ENV ===
load_dotenv()
app = Flask(__name__)

# === ENV & CONFIG ===
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME_USERS = os.getenv("SHEET_NAME_USERS")
SHEET_NAME_LOGS = os.getenv("SHEET_NAME_LOGS")
SHEET_NAME_SUBS = os.getenv("SHEET_NAME_SUBS", "Subscribers")
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
subs_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_SUBS)

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

# === LOGGING ===
def log_usage(user_id, action, detail):
    now = datetime.now().isoformat()
    try:
        logs_sheet.append_row([now, user_id, action, detail])
    except Exception as e:
        print("Log error:", e)

def log_lucky_fail():
    now = datetime.now().isoformat()
    try:
        logs_sheet.append_row([now, "SYSTEM", "lucky_error", "ดึงเลขเด็ดไม่สำเร็จ"])
    except Exception as e:
        print("Log error:", e)

# === FLEX ===
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

# === FETCH ===
cache = {"data": None, "last_update": datetime.min, "last_sent_date": None}

def fetch_lucky_auto():
    now = datetime.now()
    if cache["data"] and now - cache["last_update"] < timedelta(hours=6):
        return cache["data"]

    try:
        r = requests.get("https://www.dailynews.co.th/news/2533714/", timeout=5)
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
        log_lucky_fail()
        return cache["data"] or {}

# === SUBSCRIBE NOTIFY ===
def notify_new_lucky():
    now = datetime.now()
    if cache["last_sent_date"] == now.strftime("%Y-%m-%d"):
        return
    lucky_data = fetch_lucky_auto()
    if not lucky_data:
        return

    users = subs_sheet.col_values(1)[1:]
    for uid in users:
        try:
            send_flex_lucky_numbers(uid, lucky_data)
        except:
            pass
    cache["last_sent_date"] = now.strftime("%Y-%m-%d")

threading.Thread(target=lambda: [time.sleep(10), notify_new_lucky()]).start()

# === ROUTES ===
@app.route("/")
def home():
    return "ดวงจิต AI พร้อมใช้งานฟรีแล้ว 🎉"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    for event in data.get("events", []):
        if event["type"] != "message": continue
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]
        msg = event["message"].get("text", "").strip()

        if msg == "เลขเด็ดงวดนี้":
            lucky_data = fetch_lucky_auto()
            send_line_message(reply_token, "📥 กำลังดึงเลขเด็ดล่าสุด...")
            send_flex_lucky_numbers(user_id, lucky_data)
            subs = subs_sheet.col_values(1)
            if user_id not in subs:
                subs_sheet.append_row([user_id])
            log_usage(user_id, "เลขเด็ด", "ขอเลขเด็ดงวดนี้")
            continue

        elif re.match(r'^\d{2,3}$', msg):
            lucky_data = fetch_lucky_auto()
            hits = []
            for k,v in lucky_data.items():
                if msg in v.get("two", []) or msg in v.get("three", []) or msg in v.get("chup", []):
                    hits.append(f"✅ {k} มีเลขนี้!")
            reply = "\n".join(hits) if hits else f"❌ ไม่พบเลข {msg} ในเลขเด็ดงวดนี้"
            send_line_message(reply_token, reply)
            continue

        send_line_message(reply_token, "🧘‍♀️ หมอดูกำลังทำนาย รอสักครู่...")
        threading.Thread(target=lambda: [push_line_message(user_id, get_fortune(msg)), log_usage(user_id, "หมอดูฟรี", msg)]).start()

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
        return jsonify({"status": "success", "data": users_sheet.get_all_records()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

application = app
