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

# === LINE FUNCTIONS ===
def send_line_message(reply_token, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=body)

def push_line_message(user_id, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)

# === ตรวจสอบข้อความไทย ===
def is_valid_thai_text(text):
    pattern = r'^[\u0E00-\u0E7F0-9\s\.\,\?\!]+$'
    return bool(re.match(pattern, text))

# === ตรวจสอบและแปลงวันเกิด ===
def normalize_birthdate(text):
    match = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$', text)
    if match:
        day, month, year = map(int, match.groups())
        if year < 100:
            year += 2500
        return f"{day:02d}/{month:02d}/{year}"
    return text

# === AI วิเคราะห์จากวันเกิด ===
def get_fortune_from_birthdate(birthdate_text):
    prompt = f"""
คุณคือหมอดูไทยโบราณ ผู้เชี่ยวชาญในการดูดวงชะตาจากวันเดือนปีเกิดตามหลักโหราศาสตร์ไทย

ผู้ใช้เกิดวันที่: {birthdate_text}

โปรดวิเคราะห์ดวงชะตาโดยละเอียด พร้อมคำแนะนำเสริมดวง เช่น การทำบุญ การสวดมนต์ และข้อคิดให้กำลังใจ โดยใช้ภาษาไทยที่สุภาพ ชัดเจน และเข้าใจง่าย
"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        return f"⚠️ ข้อผิดพลาดการทำนายวันเกิด: {str(e)}"

# === AI วิเคราะห์ทั่วไป ===
def get_fortune(message):
    prompt = f"""
คุณคือหมอดูไทยโบราณ ผู้เชี่ยวชาญในศาสตร์หลากหลายแขนง เช่น ดวงความรัก การเงิน โชคลาภ การงาน สุขภาพ การทำนายฝัน การเสริมดวง การทำบุญตามแบบไทยโบราณ และการวิเคราะห์เลขเด็ดจากข่าวล่าสุดหลายสำนักทั่วประเทศ

กรุณาวิเคราะห์คำถามของผู้ถามและเลือกใช้ศาสตร์ที่เหมาะสมที่สุดในการให้คำตอบ พร้อมให้คำแนะนำอย่างนุ่มนวล สุภาพ อิงหลักความเชื่อไทย เช่น วันเกิด เลขมงคล บุญกรรม การไหว้พระ และข้อคิดที่ดี

คำถาม: "{message}"

หากคำถามมีการระบุวันเดือนปีเกิด เช่น "17-10-2536", "1/1/2520", หรือรูปแบบอื่นที่คล้ายกัน ให้พิจารณาว่าเป็นวันเกิดของผู้ถาม แล้ววิเคราะห์ดวงชะตาตามหลักโหราศาสตร์ไทย เช่น วันเกิด ปีนักษัตร ลัคนา จุดเด่น จุดอ่อน คำเตือน และแนะนำวิธีเสริมดวงตามวันเกิดนั้น ๆ

หากคำถามเกี่ยวกับ "เลขเด็ด", "หวย", หรือ "เลขมงคล", "เลขเด็ดวันนี้" ให้คุณ:

1. สมมุติว่าคุณเป็นนักข่าวหวยชื่อดัง ที่มีหน้าที่รวบรวมล่าสุดเลขเด็ดเลขดังจากหลายสำนักในประเทศไทย
2. สร้างสรุปข้อมูลของงวดปัจจุบัน (วันที่ 1 หรือ 16 ของเดือนนี้) โดยอ้างอิงจากการรายงานข่าว และแนวโน้มเลขที่ถูกพูดถึง
3. ให้รูปแบบชัดเจน เข้าใจง่าย และเหมาะกับผู้อ่านใน LINE โดยแยกหัวข้อ และใช้ Emoji เพื่อความน่าสนใจ

กรุณาแสดงผลในรูปแบบนี้:
- 📌 ม้าวิ่ง: แสดงเลขท้าย 2 ตัว และเลขท้าย 3 ตัว งวดล่าสุด
- 📌 แม่น้ำหนึ่ง: แสดงเลขท้าย 2 ตัว และเลขท้าย 3 ตัว งวดล่าสุด
- 📌 เพชรกล้า: แสดงเลขเด่น, คู่เลขจับเด่น งวดล่าสุด
- 📌 เลขธูป (ถ้ามี): แสดงเลขธูป 3 ตัวจากสำนักใดก็ตาม
- 📌 เลขขันน้ำมนต์: แสดงเลขเด่นที่เห็นจากขันน้ำมนต์ งวดล่าสุด
- 📌 เลขอั้น / เลขเจ้ามือไม่รับ: ถ้ามีให้ระบุ
- 📌 เลขที่ออกบ่อยย้อนหลัง 50 งวด: แสดงเลขท้าย 2 ตัว และ 3 ตัว พร้อมสถิติ

หากไม่มีข้อมูลของบางสำนัก ให้ใส่ว่า “ยังไม่พบข้อมูล” แต่ให้จัดรูปแบบให้เหมือนกัน

สุดท้ายให้ปิดท้ายด้วยคำให้กำลังใจ เช่น:
“ขอให้โชคดี มีลาภงวดนี้นะครับ 🙏🍀”

ให้ตอบเป็นภาษาไทยทั้งหมด
"""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        return f"⚠️ ระบบหมอดู AI ขัดข้อง: {str(e)}"

# === บันทึกการใช้งาน ===
def log_usage(user_id, action, detail):
    if logs_sheet:
        try:
            logs_sheet.append_row([datetime.now().isoformat(), user_id, action, detail])
        except Exception as e:
            print("Log error:", e)

# === ส่งลิงก์เชิญเพื่อน ===
def send_invite_link(user_id):
    link = f"{PUBLIC_URL}/shared?user_id={user_id}"
    text = f"""🎁 เชิญเพื่อนของคุณมาใช้หมอดู AI 'ดวงจิต'\n\nแชร์ลิงก์นี้ให้เพื่อน:\n{link}\n\nเมื่อเพื่อนกดลิงก์นี้ คุณจะได้รับสิทธิ์ฟรีทันที 💬"""
    push_line_message(user_id, text)

# === WEBHOOK ===
@app.route("/webhook", methods=["POST"])
def webhook():
    if not request.is_json:
        return jsonify({"status": "error", "message": "Content-Type must be application/json"}), 400

    data = request.json
    for event in data.get("events", []):
        if event["type"] != "message":
            continue

        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]
        message_text = event["message"].get("text", "").strip()

        if not message_text:
            send_line_message(reply_token, "📌 กรุณาพิมพ์ข้อความเป็นภาษาไทย เช่น ถามเรื่องดวง ความฝัน หรือวันเกิด")
            continue

        if message_text == "เชิญเพื่อน":
            send_invite_link(user_id)
            continue

        if not is_valid_thai_text(message_text) and not re.search(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', message_text):
            send_line_message(reply_token, "📌 โปรดพิมพ์ข้อความเป็นภาษาไทย หรือระบุวันเกิด")
            continue

        send_line_message(reply_token, "🧘‍♀️ หมอดูกำลังวิเคราะห์ และทำนาย รอสักครู่...")

        def reply_later():
            match = re.search(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', message_text)
            if match:
                birthdate = normalize_birthdate(match.group())
                reply = get_fortune_from_birthdate(birthdate)
            else:
                reply = get_fortune(message_text)
            push_line_message(user_id, reply)
            log_usage(user_id, "ใช้งานฟรี", message_text)

        threading.Thread(target=reply_later).start()

    return jsonify({"status": "ok"})

# === รัน Local / Render ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)

application = app

