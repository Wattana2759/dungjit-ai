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

# === LOAD ENV ===
load_dotenv()
app = Flask(__name__)

# === ENV & CONFIG ===
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME_USERS = os.getenv("SHEET_NAME_USERS")
SHEET_NAME_LOGS = os.getenv("SHEET_NAME_LOGS")
LIFF_ID = os.getenv("LIFF_ID")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:5000")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")

# === SET OPENAI API KEY ===
openai.api_key = OPENAI_API_KEY

# === GOOGLE SHEETS SETUP ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = Credentials.from_service_account_file(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"), scopes=scope)
client_sheet = gspread.authorize(credentials)
sheet_users = client_sheet.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
sheet_logs = client_sheet.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === ROUTES ===
@app.route("/")
def home():
    return "หมอดูดวงจิต AI พร้อมให้บริการ 🎯"

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json()
    events = payload.get("events", [])
    for event in events:
        if event["type"] == "message":
            reply_token = event["replyToken"]
            user_id = event["source"]["userId"]
            text = event["message"]["text"]
            response_text = get_fortune(text)
            reply_message(reply_token, response_text)
    return jsonify({"status": "ok"})

# === FUNCTION: ตอบกลับ LINE ===
def reply_message(reply_token, message):
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message}]
    }
    requests.post(url, headers=headers, json=payload)

# === FUNCTION: ดูดวงจาก GPT ===
def get_fortune(text):
    try:
        prompt = f"""คุณคือหมอดูไทยชื่อ "หมอดวงจิต" ใช้ภาษาสุภาพ ตอบดวงชะตาจากข้อความผู้ใช้: "{text}" โดยให้คำทำนายที่ลึกซึ้ง จริงใจ และเข้าใจง่าย"""
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        result = response.choices[0].message["content"].strip()
        return result
    except Exception as e:
        return "ขออภัย ระบบหมอดู AI ขัดข้องชั่วคราว 🛠️"

# === FUNCTION: OCR สลิป (ตัวอย่างเบื้องต้น) ===
@app.route("/ocr", methods=["POST"])
def ocr():
    if 'image' not in request.files:
        return jsonify({"error": "no file"})
    file = request.files['image']
    image = Image.open(file.stream)
    text = pytesseract.image_to_string(image, lang="tha+eng")
    return jsonify({"text": text})

# === BASIC ADMIN AUTH ===
def require_basic_auth():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
        return Response("กรุณาเข้าสู่ระบบ", 401, {"WWW-Authenticate": "Basic realm='Login Required'"})

@app.route("/admin")
def admin_dashboard():
    auth = require_basic_auth()
    if auth: return auth
    return "Dashboard ผู้ดูแลระบบ (อยู่ระหว่างพัฒนา)"

# === GUNICORN ENTRY POINT ===
application = app

