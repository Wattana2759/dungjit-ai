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
import openai  # ← ใช้เวอร์ชันใหม่
from werkzeug.utils import secure_filename

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
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")

# === SETUP GOOGLE SHEETS ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = Credentials.from_service_account_file("google-credentials.json", scopes=scope)
client_gsheet = gspread.authorize(credentials)
sheet_users = client_gsheet.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
sheet_logs = client_gsheet.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === SETUP OpenAI ===
openai.api_key = OPENAI_API_KEY

# === ROUTES ===
@app.route("/")
def index():
    return "ดวงจิต AI พร้อมให้บริการ"

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        body = request.get_json()
        events = body.get("events", [])
        for event in events:
            if event["type"] == "message":
                reply_token = event["replyToken"]
                user_id = event["source"]["userId"]
                message_text = event["message"]["text"]

                # ตรวจสอบ quota / สิทธิ์ใช้งาน
                if not check_user_permission(user_id):
                    reply_line(reply_token, "❌ กรุณาแนบสลิปชำระเงินก่อนใช้งานได้ที่: " + PUBLIC_URL + "/upload")
                    return "OK"

                # เรียก GPT
                reply = ask_openai(message_text)
                reply_line(reply_token, reply)

                # บันทึก log
                sheet_logs.append_row([str(datetime.now()), user_id, message_text, reply])
        return "OK"
    except Exception as e:
        print("❌ Webhook error:", e)
        return jsonify({"status": "error", "message": str(e)})

def reply_line(reply_token, text):
    headers = {
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=data)

def ask_openai(prompt):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        return "ขออภัย ระบบหมอดู AI ขัดข้องชั่วคราว"

def check_user_permission(user_id):
    try:
        users = sheet_users.get_all_records()
        for user in users:
            if user["UserID"] == user_id and int(user.get("Quota", 0)) > 0:
                # หัก quota
                row = users.index(user) + 2
                sheet_users.update_cell(row, 3, int(user["Quota"]) - 1)
                return True
        return False
    except Exception as e:
        print("❌ Permission check error:", e)
        return False

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files.get("slip")
        user_id = request.form.get("user_id")
        if file:
            filename = secure_filename(file.filename)
            path = os.path.join("uploads", filename)
            file.save(path)

            # OCR
            text = pytesseract.image_to_string(Image.open(path), lang="tha+eng")

            # ตรวจยอดเงิน
            match = re.search(r"(โอน|จำนวนเงิน|ยอด)[^\d]*([\d,]+\.\d{2})", text)
            if match:
                amount = float(match.group(2).replace(",", ""))
                usage = int(amount)
                # อัปเดตสิทธิ์ใน Google Sheet
                add_or_update_user(user_id, usage)
                return "✅ ระบบได้รับสลิปแล้ว คุณได้รับสิทธิ์ " + str(usage) + " ข้อความ"
            return "❌ ไม่พบยอดเงินในสลิป กรุณาตรวจสอบใหม่"
    return render_template("upload.html", liff_id=LIFF_ID)

def add_or_update_user(user_id, quota):
    users = sheet_users.get_all_records()
    for i, user in enumerate(users):
        if user["UserID"] == user_id:
            row = i + 2
            new_quota = int(user.get("Quota", 0)) + quota
            sheet_users.update_cell(row, 3, new_quota)
            return
    # ถ้ายังไม่มี user นี้
    sheet_users.append_row([user_id, str(datetime.now()), quota])

@app.route("/admin", methods=["GET"])
def admin():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
        return Response("กรุณาเข้าสู่ระบบ", 401, {"WWW-Authenticate": 'Basic realm="Login Required"'})
    users = sheet_users.get_all_records()
    logs = sheet_logs.get_all_records()
    return render_template("admin.html", users=users, logs=logs)

if __name__ == "__main__":
    app.run(debug=True)

