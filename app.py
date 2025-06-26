from flask import Flask, request, jsonify
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import openai
import threading
import time
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
    print("\u274c \u0e44\u0e21\u0e48\u0e1e\u0e1a Users Sheet:", e)

try:
    logs_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)
except Exception as e:
    logs_sheet = None
    print("\u274c \u0e44\u0e21\u0e48\u0e1e\u0e1a Logs Sheet:", e)

# === LINE FUNCTIONS ===
def send_line_message(reply_token, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=body)

def push_line_message(user_id, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)

# === UTILITIES ===
def is_valid_thai_text(text):
    return bool(re.match(r'^[\u0E00-\u0E7F0-9\s\.,\?!]+$', text))

def normalize_birthdate(text):
    match = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$', text)
    if match:
        d, m, y = map(int, match.groups())
        if y < 100: y += 2500
        return f"{d:02d}/{m:02d}/{y}"
    return text

def get_fortune_from_birthdate(birthdate):
    prompt = f"""
คุณคือหมอดูไทยโบราณ ผู้เชี่ยวชาญในการดูดวงชะตาจากวันเดือนปีเกิดตามหลักโหราศาสตร์ไทย

ผู้ใช้เกิดวันที่: {birthdate}

โปรดวิเคราะห์ดวงชะตาโดยละเอียด พร้อมคำแนะนำเสริมดวง เช่น การทำบุญ การสวดมนต์ และข้อคิดให้กำลังใจ โดยใช้ภาษาไทยที่สุภาพ ชัดเจน และเข้าใจง่าย
"""
    try:
        res = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return res.choices[0].message["content"].strip()
    except Exception as e:
        return f"\u26a0\ufe0f ข้อผิดพลาด: {str(e)}"

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
- \ud83d\udccc ม้าวิ่ง: แสดงเลขท้าย 2 ตัว และเลขท้าย 3 ตัว งวดล่าสุด
- \ud83d\udccc แม่น้ำหนึ่ง: แสดงเลขท้าย 2 ตัว และเลขท้าย 3 ตัว งวดล่าสุด
- \ud83d\udccc เพชรกล้า: แสดงเลขเด่น, คู่เลขจับเด่น งวดล่าสุด
- \ud83d\udccc เลขธูป (ถ้ามี): แสดงเลขธูป 3 ตัวจากสำนักใดก็ตาม
- \ud83d\udccc เลขขันน้ำมนต์: แสดงเลขเด่นที่เห็นจากขันน้ำมนต์ งวดล่าสุด
- \ud83d\udccc เลขอั้น / เลขเจ้ามือไม่รับ: ถ้ามีให้ระบุ
- \ud83d\udccc เลขที่ออกบ่อยย้อนหลัง 10 งวด: แสดงเลขท้าย 2 ตัว และ 3 ตัว พร้อมสถิติ

หากไม่มีข้อมูลของบางสำนัก ให้ใส่ว่า “ยังไม่พบข้อมูล” แต่ให้จัดรูปแบบให้เหมือนกัน

สุดท้ายให้ปิดท้ายด้วยคำให้กำลังใจ เช่น:
“ขอให้โชคดี มีลาภงวดนี้นะครับ \ud83d\ude4f\ud83c\udf40”

ให้ตอบเป็นภาษาไทยทั้งหมด
"""
    try:
        res = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return res.choices[0].message["content"].strip()
    except Exception as e:
        return f"\u26a0\ufe0f ระบบขัดข้อง: {str(e)}"

def log_usage(user_id, action, detail):
    if logs_sheet:
        try:
            logs_sheet.append_row([datetime.now().isoformat(), user_id, action, detail])
        except Exception as e:
            print("Log error:", e)

# === WEBHOOK ===
@app.route("/webhook", methods=["POST"])
def webhook():
    if not request.is_json:
        return jsonify({"error": "Invalid content"}), 400

    data = request.json
    for event in data.get("events", []):
        if event["type"] != "message":
            continue

        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]
        message = event["message"].get("text", "").strip()

        if not message:
            send_line_message(reply_token, "\ud83d\udccc กรุณาพิมพ์คำถามหรือวันเกิด เช่น 17/10/2536")
            continue

        if not is_valid_thai_text(message) and not re.search(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', message):
            send_line_message(reply_token, "\ud83d\udccc โปรดพิมพ์ข้อความเป็นภาษาไทย เช่น ดวง ความรัก หรือวันเกิด 1/1/2520")
            continue

        send_line_message(reply_token, "\ud83d\udd2e กำลังดูดวงให้คุณ กรุณารอสักครู่...")

        def reply_later():
            match = re.search(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', message)
            reply = get_fortune_from_birthdate(normalize_birthdate(match.group())) if match else get_fortune(message)
            push_line_message(user_id, reply)
            log_usage(user_id, "ใช้งานฟรี", message)

            try:
                records = users_sheet.get_all_records()
                for i, row in enumerate(records, start=2):
                    if row["user_id"] == user_id:
                        usage = int(row.get("usage", 0))
                        invite_sent = str(row.get("invite_sent", "")).lower().strip()
                        if usage >= 5 and invite_sent != "true":
                            text = (
                                "\ud83d\ude4f ขอบคุณที่ใช้งานหมอดู AI 'ดวงจิต' บ่อยมาก!\n"
                                "เพื่อสนับสนุนเรา ขอเชิญคุณช่วยแชร์ลิงก์เพิ่มเพื่อนให้เพื่อนของคุณ \ud83d\udcac\n\n"
                                "เพิ่มเพื่อนที่นี่เลย \ud83d\udc49 https://lin.ee/7LgReP1"
                            )
                            push_line_message(user_id, text)
                            users_sheet.update_cell(i, 7, "TRUE")
                        break
            except Exception as e:
                print("\u274c invite check error:", e)

        threading.Thread(target=reply_later).start()

    return jsonify({"status": "ok"})

# === HEALTH CHECK ===
@app.route("/healthz")
def healthz():
    return "OK", 200

# === AUTO PING TO PREVENT SLEEP ===
def auto_ping():
    while True:
        try:
            requests.get(f"{PUBLIC_URL}/healthz", timeout=10)
            print("\ud83d\udd01 Auto-ping sent")
        except Exception as e:
            print("\u26a0\ufe0f Auto-ping error:", e)
        time.sleep(300)

threading.Thread(target=auto_ping, daemon=True).start()

# === START ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)

application = app
