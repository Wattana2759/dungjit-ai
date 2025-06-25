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

# ตรวจสอบว่าเปิด sheet ได้หรือไม่
try:
    users_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
except Exception as e:
    users_sheet = None
    print("❌ ไม่พบ Users Sheet:", e)

try:
    logs_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)
except Exception as e:
    logs_sheet = None
    print("❌ ไม่พบ Logs Sheet:", e)

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

# === AI หมอดูไทย ===
def get_fortune(message):
    if "ความรัก" in message:
        prompt = f"""คุณคือหมอดูไทยโบราณ ผู้เชี่ยวชาญด้านดวงความรัก...
คำถาม: "{message}"
ตอบเป็นภาษาไทยเท่านั้น โดยเน้นความแม่นยำ น่าเชื่อถือ และให้ข้อคิดที่ดีแก่ผู้ถาม"""
    elif "เงิน" in message or "การเงิน" in message or "โชคลาภ" in message:
        prompt = f"""คุณคือหมอดูไทยโบราณ ผู้มีความรู้ด้านโชคลาภ...
คำถาม: "{message}"
ตอบด้วยความสุภาพ และให้ผู้ถามมีความหวังในการจัดการชีวิตการเงิน"""
    elif "ฝัน" in message:
        prompt = f"""คุณคือหมอดูไทยโบราณ ผู้เชี่ยวชาญด้านการทำนายฝัน...
คำถาม: "{message}"
ตอบด้วยภาษาไทยแบบสุภาพ และอิงตำราโบราณในการทำนายฝัน"""
    elif "ทำบุญ" in message or "เสริมดวง" in message or "บารมี" in message:
        prompt = f"""คุณคือหมอดูไทย ผู้มีความเข้าใจเรื่องบุญบารมี...
คำถาม: "{message}"
ตอบด้วยน้ำเสียงเมตตา ให้กำลังใจ และเสริมแรงศรัทธา"""
    elif "ดวง" in message or "ดวงวันนี้" in message or "ดวงเดือน" in message:
        prompt = f"""คุณคือหมอดูไทยโบราณ ผู้สามารถดูดวงรายวันและรายเดือน...
คำถาม: "{message}"
ตอบด้วยภาษาไทยสุภาพแบบหมอดู พร้อมเสนอแนวทางเสริมดวง"""
    else:
        prompt = f"""คุณคือหมอดูไทยโบราณ ที่มีความรู้ในศาสตร์แห่งดวงชะตา...
คำถาม: "{message}"
ตอบด้วยความเข้าใจ ให้คำทำนายที่แม่นยำ พร้อมข้อคิดที่ดี"""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message["content"].strip()
    except openai.error.OpenAIError as e:
        return f"⚠️ ระบบหมอดู AI ขัดข้อง: {str(e)}"
    except Exception as e:
        return f"⚠️ ข้อผิดพลาดไม่คาดคิด: {str(e)}"

# === LOGGING (แยก Thread) ===
def log_usage(user_id, action, detail):
    now = datetime.now().isoformat()
    if logs_sheet:
        try:
            logs_sheet.append_row([now, user_id, action, detail])
        except Exception as e:
            print("Log error:", e)

# === ตรวจสอบข้อความไทย + เลข ===
def is_valid_thai_text(text):
    pattern = r'^[\u0E00-\u0E7F0-9\s\.\,\?\!]+$'
    return bool(re.match(pattern, text))

# === ฟังก์ชันแชร์ลิงก์ให้เพื่อน ===
def send_invite_link(user_id):
    link = f"{PUBLIC_URL}/shared?user_id={user_id}"
    text = f"""🎁 เชิญเพื่อนของคุณมาใช้หมอดู AI 'ดวงจิต'\n\nแชร์ลิงก์นี้ให้เพื่อน:\n{link}\n\nเมื่อเพื่อนกดลิงก์นี้ คุณจะได้รับสิทธิ์ฟรีทันที 💬"""
    push_line_message(user_id, text)

# === ROUTES ===
@app.route("/")
def home():
    return "ดวงจิต AI พร้อมใช้งานฟรีแล้ว 🎉"

@app.route("/webhook", methods=["POST"])
def webhook():
    if not request.is_json:
        return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400

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

        if message_text == "เชิญเพื่อน":
            send_invite_link(user_id)
            continue

        if not is_valid_thai_text(message_text):
            send_line_message(reply_token, "📌 โปรดใช้เฉพาะข้อความภาษาไทย หรือเลขเท่านั้น เช่น \"ฝันเห็นงู\" หรือ \"ดวงการเงินวันนี้\"")
            continue

        send_line_message(reply_token, "🧘‍♀️ หมอดูกำลังทำนาย รอสักครู่...")

        def reply_later():
            reply = get_fortune(message_text)
            push_line_message(user_id, reply)
            log_usage(user_id, "ใช้งานฟรี", message_text)

        threading.Thread(target=reply_later).start()

    return jsonify({"status": "ok"})

@app.route("/shared")
def shared_page():
    user_id = request.args.get("user_id")
    return f"""<h2>🙏 ขอบคุณที่เข้าร่วม!</h2>
<p>คุณถูกเชิญโดยผู้ใช้ <code>{user_id}</code></p>
<p>หากคุณเพิ่ม LINE Official Account: <b>@duangjitai</b> แล้ว คุณจะได้รับสิทธิ์ทำนายฟรี</p>"""

@app.route("/admin")
def admin_dashboard():
    auth = require_basic_auth()
    if auth: return auth
    if users_sheet:
        records = users_sheet.get_all_records()
        return render_template("admin_dashboard.html", users=records)
    else:
        return "❌ Users Sheet ยังไม่พร้อมใช้งาน", 500

@app.route("/test-sheet")
def test_sheet():
    try:
        if users_sheet:
            data = users_sheet.get_all_records()
            return jsonify({"status": "success", "data": data})
        else:
            return jsonify({"status": "error", "message": "Users Sheet ยังไม่พร้อมใช้งาน"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# === RUN APP (For Render) ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)

# === EXPORT FOR RENDER ===
application = app

