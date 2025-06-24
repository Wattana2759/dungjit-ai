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

# === AUTH ===
def require_basic_auth():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
        return Response("กรุณาเข้าสู่ระบบ", 401, {"WWW-Authenticate": "Basic realm='Admin Access'"})

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

def add_or_update_user(user_id, name, added_quota, slip_file):
    user, row = get_user(user_id)
    now = datetime.now().isoformat()
    if user:
        new_quota = int(user["paid_quota"]) + added_quota
        users_sheet.update(f"C{row}:F{row}", [[user["usage"], new_quota, slip_file, now]])
    else:
        users_sheet.append_row([user_id, name, 0, added_quota, slip_file, now])

def log_usage(user_id, action, detail):
    now = datetime.now().isoformat()
    if not is_duplicate_log(user_id, detail):
        logs_sheet.append_row([now, user_id, action, detail])

def is_duplicate_log(user_id, message_text, max_rows=20):
    try:
        recent_rows = logs_sheet.get_all_values()[-max_rows:]
        for row in recent_rows:
            if len(row) >= 4 and row[1] == user_id and row[3] == message_text:
                return True
        return False
    except: return False

# === LINE MESSAGES ===
def send_line_message(reply_token, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=body)

def push_line_message(user_id, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)

# === หมอดู AI GPT ===
def get_fortune(message):
    prompt = f"""คุณคือหมอดูไทยโบราณ ผู้มีญาณหยั่งรู้ พูดจาเคร่งขรึม สุภาพ ตอบคำถามเรื่องดวงชะตา ความรัก การเงิน และความฝัน\n\nผู้ใช้ถาม: "{message}"\nคำตอบของหมอดู:"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        return f"ขออภัย ระบบหมอดู AI ขัดข้อง: {str(e)}"

# === OCR ===
def extract_payment_info(text):
    name = re.search(r"(ชื่อ[^\n\r]+)", text)
    amount = re.search(r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(บาท|฿)?", text)
    return {
        "amount": amount.group(1).replace(",", "") if amount else None,
        "name": name.group(1).strip() if name else None
    }

# === ROUTES ===
@app.route("/")
def home():
    return "ดวงจิต AI พร้อมใช้งานแล้ว"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    for event in data.get("events", []):
        if event["type"] != "message" or event["message"]["type"] != "text":
            continue
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]
        message_text = event["message"]["text"].strip()

        user, _ = get_user(user_id)
        if message_text.lower() == "/ดูสิทธิ์":
            if not user:
                send_line_message(reply_token, "คุณยังไม่มีสิทธิ์ใช้งาน")
            else:
                send_line_message(reply_token, f"คุณใช้ไปแล้ว {user['usage']} / {user['paid_quota']} ครั้ง")
            continue

        if not user or int(user["paid_quota"]) <= int(user["usage"]):
            push_line_message(user_id, "📌 กรุณาชำระเงินผ่าน PromptPay เพื่อใช้งาน")
            push_line_message(user_id, "📤 แนบสลิปหลังชำระเงินที่นี่: https://liff.line.me/" + LIFF_ID)
            continue

        reply = get_fortune(message_text)
        send_line_message(reply_token, reply)
        update_user(user_id, usage=int(user["usage"]) + 1)
        log_usage(user_id, "ใช้สิทธิ์", message_text)

    return jsonify({"status": "ok"})

@app.route("/upload-slip", methods=["GET", "POST"])
def upload_slip():
    if request.method == "POST":
        user_id = request.form.get("user_id")
        user_name = request.form.get("user_name")
        file = request.files.get("file")
        if not user_id or not file:
            return "กรุณากรอกข้อมูลให้ครบ", 400
        filename = f"slip_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
        os.makedirs("static/slips", exist_ok=True)
        path = f"static/slips/{filename}"
        file.save(path)
        ocr_text = pytesseract.image_to_string(Image.open(path), lang="eng+tha")
        info = extract_payment_info(ocr_text)
        amount_paid = int(float(info["amount"])) if info["amount"] else 0
        add_or_update_user(user_id, user_name, amount_paid, filename)
        push_line_message(user_id, f"📥 ได้รับสลิปแล้ว เพิ่มสิทธิ์ {amount_paid} ครั้ง ✅")
        log_usage(user_id, "แนบสลิป", f"OCR: {info}")
        return render_template("success.html", user_id=user_id)
    return render_template("upload_form.html")

@app.route("/upload-slip-liff")
def upload_slip_liff():
    return render_template("upload_slip_liff.html", liff_id=LIFF_ID)

@app.route("/success")
def success_page():
    return render_template("success.html", user_id=request.args.get("user_id", "ไม่ทราบ"))

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

