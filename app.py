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
from openai import OpenAI

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
client = OpenAI(api_key=OPENAI_API_KEY)

# === GOOGLE SHEETS ===
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
credentials = Credentials.from_service_account_file(
    os.getenv("GOOGLE_APPLICATION_CREDENTIALS"), scopes=scopes
)
gc = gspread.authorize(credentials)
sheet_users = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
sheet_logs = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === LINE API ===
def reply_text(reply_token, text):
    headers = {
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=data)

def push_flex_message(user_id, alt_text, contents):
    headers = {
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "to": user_id,
        "messages": [{
            "type": "flex",
            "altText": alt_text,
            "contents": contents
        }]
    }
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=data)

# === OCR ===
def extract_amount_and_name(image_path):
    image = Image.open(image_path)
    text = pytesseract.image_to_string(image, lang="tha+eng")
    amount_match = re.search(r'([0-9,]+\.\d{2})\s*บาท', text)
    name_match = re.search(r'(นาย|นางสาว|นาง|คุณ)\s?[^\s\n]+', text)
    amount = amount_match.group(1).replace(",", "") if amount_match else None
    name = name_match.group(0) if name_match else None
    return amount, name, text

# === ROUTES ===
@app.route("/")
def home():
    return "ดวงจิต AI พร้อมทำงาน"

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.json
    try:
        for event in payload["events"]:
            reply_token = event["replyToken"]
            user_id = event["source"]["userId"]
            if event["type"] == "message" and event["message"]["type"] == "text":
                text = event["message"]["text"]
                # ตรวจสอบสิทธิ์ใช้งาน
                usage = sheet_users.find(user_id)
                if usage:
                    row = usage.row
                    quota = int(sheet_users.cell(row, 3).value)
                    if quota > 0:
                        response = call_openai(text)
                        reply_text(reply_token, response)
                        sheet_users.update_cell(row, 3, quota - 1)
                        sheet_logs.append_row([datetime.now().isoformat(), user_id, text])
                    else:
                        reply_text(reply_token, "❌ คุณใช้สิทธิ์ครบแล้ว กรุณาเติมเงินหรือแนบสลิปการโอน")
                else:
                    # สมัครใหม่
                    sheet_users.append_row([user_id, datetime.now().isoformat(), 0])
                    reply_text(reply_token, "👋 ยินดีต้อนรับสู่ดวงจิต AI\nกรุณาเติมเงินและแนบสลิปเพื่อเริ่มใช้งาน")

            elif event["type"] == "message" and event["message"]["type"] == "image":
                image_id = event["message"]["id"]
                image_data = requests.get(
                    f"https://api-data.line.me/v2/bot/message/{image_id}/content",
                    headers={"Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
                ).content
                image_path = f"static/{image_id}.jpg"
                with open(image_path, "wb") as f:
                    f.write(image_data)
                amount, name, full_text = extract_amount_and_name(image_path)
                if amount:
                    # เพิ่ม quota ตามจำนวนเงิน
                    usage = sheet_users.find(user_id)
                    row = usage.row if usage else sheet_users.row_count + 1
                    old_quota = int(sheet_users.cell(row, 3).value) if usage else 0
                    new_quota = old_quota + int(float(amount))
                    if usage:
                        sheet_users.update_cell(row, 3, new_quota)
                    else:
                        sheet_users.append_row([user_id, datetime.now().isoformat(), new_quota])
                    reply_text(reply_token, f"✅ ตรวจพบยอดเงิน {amount} บาท\nเพิ่มสิทธิ์ให้เรียบร้อยแล้ว ({new_quota} ครั้ง)")
                else:
                    reply_text(reply_token, "❌ ไม่สามารถตรวจสอบสลิปได้ กรุณาลองใหม่อีกครั้ง")

    except Exception as e:
        print("❌ ERROR:", e)
        reply_text(reply_token, "ขออภัย ระบบหมอดู AI ขัดข้องชั่วคราว")
    return "OK"

# === OPENAI ===
def call_openai(prompt):
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"ขออภัย ระบบขัดข้อง: {e}"

# === LIFF / แนบสลิป ===
@app.route("/upload-slip", methods=["GET", "POST"])
def upload_slip():
    if request.method == "POST":
        file = request.files["slip"]
        user_id = request.form["user_id"]
        image_path = f"static/{user_id}_{datetime.now().timestamp()}.jpg"
        file.save(image_path)
        amount, name, text = extract_amount_and_name(image_path)
        if amount:
            usage = sheet_users.find(user_id)
            row = usage.row if usage else sheet_users.row_count + 1
            old_quota = int(sheet_users.cell(row, 3).value) if usage else 0
            new_quota = old_quota + int(float(amount))
            if usage:
                sheet_users.update_cell(row, 3, new_quota)
            else:
                sheet_users.append_row([user_id, datetime.now().isoformat(), new_quota])
            return f"✅ ระบบตรวจสอบสลิปแล้ว: {amount} บาท เพิ่มสิทธิ์เป็น {new_quota} ครั้ง"
        else:
            return "❌ ไม่พบยอดเงินในสลิป กรุณาแนบใหม่"
    return render_template("upload_slip.html", liff_id=LIFF_ID)

# === BASIC ADMIN LOGIN ===
@app.route("/admin")
def admin():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
        return Response("Unauthorized", 401, {"WWW-Authenticate": "Basic realm='Login Required'"})
    users = sheet_users.get_all_records()
    return render_template("admin.html", users=users)

# === MAIN ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)

