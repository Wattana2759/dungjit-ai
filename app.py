# app.py (รวมทั้งหมดแบบใช้ Google Sheets แทน SQLite พร้อม LIFF, Chart.js, OCR)

from flask import Flask, request, jsonify, render_template, Response
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image
import pytesseract
import re
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

# === Load ENV ===
load_dotenv()
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LIFF_ID = os.getenv("LIFF_ID")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:5000")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")

app = Flask(__name__)
client = OpenAI(api_key=OPENAI_API_KEY)

# === Google Sheets Setup ===
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file("google-credentials.json", scopes=SCOPES)
gc = gspread.authorize(creds)
users_sheet = gc.open_by_key(SHEET_ID).worksheet("Users")
logs_sheet = gc.open_by_key(SHEET_ID).worksheet("Logs")

# === Auth ===
def require_basic_auth():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
        return Response("กรุณาเข้าสู่ระบบ", 401, {"WWW-Authenticate": "Basic realm='Admin Access'"})

# === Google Sheets Functions ===
def get_user(line_id):
    records = users_sheet.get_all_records()
    for idx, row in enumerate(records):
        if row["user_id"] == line_id:
            row["_row"] = idx + 2
            return row
    return None

def update_user(line_id, usage=None, paid_quota=None, slip=None):
    user = get_user(line_id)
    if not user:
        users_sheet.append_row([line_id, "new", usage or 0, paid_quota or 0, slip or "", datetime.now().isoformat()])
    else:
        if usage is not None:
            users_sheet.update_cell(user["_row"], 3, usage)
        if paid_quota is not None:
            users_sheet.update_cell(user["_row"], 4, paid_quota)
        if slip is not None:
            users_sheet.update_cell(user["_row"], 5, slip)
        users_sheet.update_cell(user["_row"], 6, datetime.now().isoformat())

def log_usage(line_id, action, detail):
    logs_sheet.append_row([datetime.now().isoformat(), line_id, action, detail])

# === LINE Messaging ===
def send_line_message(reply_token, text):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    body = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=body)

def push_line_message(user_id, text):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    body = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)

# === Flex ===
def send_payment_request(user_id):
    flex_qr = {
        "type": "flex",
        "altText": "กรุณาชำระเงินก่อนแนบสลิป",
        "contents": {
            "type": "bubble",
            "hero": {"type": "image", "url": f"{PUBLIC_URL}/static/qr_promptpay.png", "size": "full", "aspectRatio": "1:1", "aspectMode": "cover"},
            "body": {"type": "box", "layout": "vertical", "contents": [
                {"type": "text", "text": "📌 สแกนจ่ายผ่าน PromptPay", "weight": "bold", "size": "md"},
                {"type": "text", "text": "บัญชี: นาย วัฒนา จันดาหาร", "size": "sm", "wrap": True},
                {"type": "text", "text": "คำถามละ 1 บาท — แนบสลิปภายหลัง", "size": "sm", "wrap": True}
            ]}
        }
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json={"to": user_id, "messages": [flex_qr]})

def send_flex_upload_link(user_id):
    flex_message = {
        "type": "flex",
        "altText": "แนบสลิปเพื่อเปิดสิทธิ์ใช้งาน ดวงจิต AI คำถามละ 1 บาท เท่านั้น!",
        "contents": {
            "type": "bubble",
            "hero": {"type": "image", "url": f"{PUBLIC_URL}/static/banner.jpg", "size": "full", "aspectRatio": "16:9", "aspectMode": "cover"},
            "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "แนบสลิปเพื่อรับสิทธิ์ใช้งานดวงจิต หมอดู AI", "weight": "bold", "size": "md", "wrap": True}]},
            "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [{"type": "button", "style": "primary", "color": "#06c755", "action": {"type": "uri", "label": "แนบสลิปตอนนี้", "uri": f"{PUBLIC_URL}/upload-slip-liff"}}]}
        }
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json={"to": user_id, "messages": [flex_message]})

# === Fortune (GPT) ===
def get_fortune(message):
    prompt = f"""คุณคือหมอดูไทยโบราณ ผู้มีญาณหยั่งรู้ พูดจาเคร่งขรึม สุภาพ ตอบคำถามเรื่องดวงชะตา ความรัก การเงิน และความฝัน\n\nผู้ใช้ถาม: \"{message}\"\nคำตอบของหมอดู:"""
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ OpenAI Error:", e)
        return "ขออภัย ระบบหมอดู AI ไม่สามารถให้คำตอบได้ในขณะนี้ กำลังปรับปรุงระบบ"

# === OCR ===
def extract_payment_info(text):
    name = re.search(r'(ชื่อ[^\n\r]+)', text)
    amount = re.search(r'(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(บาท|฿)?', text)
    return {
        'amount': amount.group(1).replace(',', '') if amount else None,
        'name': name.group(1).strip() if name else None
    }

# === Routes ===
@app.route("/")
def home():
    return "ดวงจิต AI พร้อมใช้งานแล้ว"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if "events" not in data:
        return jsonify(status="ignored")

    for event in data["events"]:
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]
        if event.get("deliveryContext", {}).get("isRedelivery"):
            continue

        user = get_user(user_id)

        if event["type"] == "follow":
            push_line_message(user_id, "🙏 ยินดีต้อนรับสู่ ดวงจิต AI!")
            return jsonify(status="followed")

        if event["type"] == "message":
            message_text = event["message"].get("text", "")

            if message_text.strip().lower() == "/ดูสิทธิ์":
                if not user:
                    send_line_message(reply_token, "คุณยังไม่มีสิทธิ์ใช้งาน")
                else:
                    send_line_message(reply_token, f"คุณใช้ไปแล้ว {user['usage']} ครั้ง / {user['paid_quota']} ครั้ง")
                continue

            if not user or user["paid_quota"] <= 0:
                push_line_message(user_id, "💸 กรุณาชำระเงิน (1 บาท = 1 คำถาม)")
                send_payment_request(user_id)
                send_flex_upload_link(user_id)
                continue

            if user["usage"] >= user["paid_quota"]:
                push_line_message(user_id, "❌ คุณใช้สิทธิ์ครบแล้ว กรุณาแนบสลิปเพื่อเติมคำถาม")
                send_flex_upload_link(user_id)
                continue

            reply = get_fortune(message_text)
            send_line_message(reply_token, reply)
            update_user(user_id, usage=user["usage"] + 1)
            log_usage(user_id, "ใช้สิทธิ์", message_text)

    return jsonify(status="ok")

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
        amount_paid = int(float(info['amount'])) if info['amount'] else 0

        update_user(user_id, paid_quota=amount_paid, slip=filename)
        log_usage(user_id, "แนบสลิป", f"OCR: {info}")
        push_line_message(user_id, f"📥 ได้รับสลิปแล้ว เพิ่มสิทธิ์ {amount_paid} ครั้งเรียบร้อย ✅")
        return render_template("success.html", user_id=user_id)

    return render_template("upload_form.html")

@app.route("/upload-slip-liff")
def upload_slip_liff():
    return render_template("upload_slip_liff.html", liff_id=LIFF_ID)

@app.route("/review-slips")
def review_slips():
    auth = require_basic_auth()
    if auth:
        return auth
    records = users_sheet.get_all_records()
    users_with_slip = [row for row in records if row['slip']]
    return render_template("review_slips.html", users=users_with_slip)

@app.route("/review-slip-action", methods=["POST"])
def review_slip_action():
    auth = require_basic_auth()
    if auth:
        return auth
    user_id = request.form.get("user_id")
    action = request.form.get("action")
    user = get_user(user_id)

    if not user:
        return "ไม่พบผู้ใช้", 404

    if action == "approve":
        update_user(user_id, paid_quota=user["paid_quota"] + 5)
        push_line_message(user_id, "✅ สลิปของคุณได้รับการอนุมัติแล้ว")
        log_usage(user_id, "admin-approve", "อนุมัติสลิป")
    elif action == "reject":
        update_user(user_id, slip="")
        push_line_message(user_id, "❌ สลิปของคุณถูกปฏิเสธ กรุณาแนบใหม่")
        log_usage(user_id, "admin-reject", "ปฏิเสธสลิป")

    return render_template("success.html", user_id=user_id)

@app.route("/admin-dashboard")
def admin_dashboard():
    auth = require_basic_auth()
    if auth:
        return auth
    logs = logs_sheet.get_all_records()
    usage_by_date = {}
    for row in logs:
        if row["action"] == "ใช้สิทธิ์":
            date = row["timestamp"][:10]
            usage_by_date[date] = usage_by_date.get(date, 0) + 1
    chart_data = sorted(usage_by_date.items())
    return render_template("admin_dashboard.html", chart_data=chart_data)

@app.route("/liff-login")
def liff_login():
    return render_template("liff_login.html", liff_id=LIFF_ID)

application = app

