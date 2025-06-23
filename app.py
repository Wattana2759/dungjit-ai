from flask import Flask, request, jsonify, render_template, Response
from openai import OpenAI
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image
import pytesseract
import gspread
from google.oauth2.service_account import Credentials
import re

# === โหลดค่า ENV ===
load_dotenv()
app = Flask(__name__)

# === CONFIG & ENV ===
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME_USERS = os.getenv("SHEET_NAME_USERS", "Users")
SHEET_NAME_LOGS = os.getenv("SHEET_NAME_LOGS", "Logs")
LIFF_ID = os.getenv("LIFF_ID")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:5000")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")

# === Google Sheets Auth ===
creds = Credentials.from_service_account_file(
    os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
client_gs = gspread.authorize(creds)
sheet_users = client_gs.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
sheet_logs = client_gs.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === LINE headers ===
line_headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
}

# === LINE Webhook ===
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        body = request.get_json()
        events = body.get("events", [])
        for event in events:
            reply_token = event["replyToken"]
            user_id = event["source"]["userId"]
            msg_type = event["message"]["type"]
            if msg_type == "text":
                user_msg = event["message"]["text"]
                ai_reply = generate_ai_response(user_msg)
                send_line_reply(reply_token, ai_reply)
                log_to_sheet(user_id, user_msg, ai_reply)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# === AI ตอบกลับ ===
def generate_ai_response(text):
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "คุณคือหมอดูไทยโบราณ พูดจาสุภาพ ใช้ภาษาไทย"},
                {"role": "user", "content": text}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "ขออภัย ระบบหมอดู AI ขัดข้องชั่วคราว"

# === ส่งข้อความกลับ LINE ===
def send_line_reply(reply_token, msg):
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": msg}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=line_headers, json=data)

# === บันทึกลง Google Sheets ===
def log_to_sheet(user_id, question, answer):
    sheet_logs.append_row([datetime.now().isoformat(), user_id, question, answer], value_input_option="USER_ENTERED")

# === หน้าแนบสลิป OCR ===
@app.route("/upload-slip", methods=["GET", "POST"])
def upload_slip():
    if request.method == "POST":
        file = request.files.get("slip")
        if file:
            image = Image.open(file.stream)
            text = pytesseract.image_to_string(image, lang="tha+eng")
            name = extract_name(text)
            amount = extract_amount(text)
            return render_template("review.html", name=name, amount=amount, raw=text)
    return render_template("upload.html")

# === ดึงชื่อจากสลิป ===
def extract_name(text):
    match = re.search(r"โอนจาก\s*(.*?)\s*(?:เลข|บัญชี)", text)
    return match.group(1).strip() if match else "ไม่พบชื่อ"

# === ดึงยอดเงินจากสลิป ===
def extract_amount(text):
    match = re.search(r"ยอดเงิน\s*([\d,]+\.\d{2})", text)
    return match.group(1).replace(",", "") if match else "ไม่พบยอด"

# === หน้า Dashboard admin ===
@app.route("/admin")
def admin_dashboard():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
        return Response("กรุณาเข้าสู่ระบบ", 401, {"WWW-Authenticate": 'Basic realm="Login Required"'})
    data = sheet_logs.get_all_records()
    return render_template("admin.html", logs=data)

# === Run แบบ Debug ทดสอบ ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)

