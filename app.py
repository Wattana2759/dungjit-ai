# ✅ app.py: พร้อมระบบแชร์เพื่อน ป้องกันการโกง + LIFF ดึง user_id อัตโนมัติ
from flask import Flask, request, jsonify, render_template, redirect
import os, requests, re, threading
from datetime import datetime
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
import openai

# === LOAD ENV ===
load_dotenv()
app = Flask(__name__)

# === CONFIG ===
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME_LOGS = os.getenv("SHEET_NAME_LOGS")
LIFF_ID = os.getenv("LIFF_ID")
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
logs_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === LINE ===
def send_line_message(reply_token, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=body)

def push_line_message(user_id, text):
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    body = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)

# === หมอดู AI ===
def get_fortune(message):
    prompt = f"คุณคือหมอดูไทยโบราณ\n\nถาม: {message}\nตอบ:"
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        return f"เกิดข้อผิดพลาด: {str(e)}"

# === ระบบแชร์ ===
def send_invite_friend_flex(user_id, count):
    flex = {
        "type": "flex",
        "altText": "🎉 ครบ 5 ครั้ง แชร์เพื่อรับสิทธิ์เพิ่ม!",
        "contents": {
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": "https://res.cloudinary.com/dwg28idpf/image/upload/v1750824745/ChatGPT_Image_25_%E0%B8%A1%E0%B8%B4.%E0%B8%A2._2568_11_10_18_mr9phf.png",
                "size": "full", "aspectMode": "cover"
            },
            "body": {
                "type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": "ครบ 5 ครั้งแล้ว!", "weight": "bold", "size": "xl"},
                    {"type": "text", "text": "แชร์บอทนี้ให้เพื่อน รับสิทธิ์ใช้งานฟรีเพิ่ม!", "size": "sm"}
                ]
            },
            "footer": {
                "type": "box", "layout": "vertical", "contents": [
                    {
                        "type": "button", "style": "primary",
                        "action": {
                            "type": "uri", "label": "แชร์ให้เพื่อน",
                            "uri": f"{PUBLIC_URL}/liff-share?referrer={user_id}"
                        }
                    }
                ]
            }
        }
    }
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json={"to": user_id, "messages": [flex]})

def has_shared_before(user_id, referrer_id):
    logs = logs_sheet.get_all_records()
    for row in logs:
        if row.get("user_id") == user_id and row.get("referrer_id") == referrer_id:
            return True
    return False

def log_usage(user_id, action, detail, referrer_id=""):
    now = datetime.now().isoformat()
    logs_sheet.append_row([now, user_id, referrer_id, action])

    if action == "ใช้งานฟรี":
        logs = logs_sheet.get_all_records()
        count = sum(1 for r in logs if r["user_id"] == user_id and r["action"] == "ใช้งานฟรี")
        if count % 5 == 0:
            send_invite_friend_flex(user_id, count)

# === webhook ===
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    for event in data.get("events", []):
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]
        if event["type"] != "message" or event["message"]["type"] != "text":
            send_line_message(reply_token, "❌ รองรับเฉพาะข้อความภาษาไทยเท่านั้น")
            return jsonify({"status": "ignored"})

        message_text = event["message"]["text"].strip()
        if not re.search(r'[\u0E00-\u0E7F]', message_text):
            send_line_message(reply_token, "📌 กรุณาพิมพ์เป็นภาษาไทยเท่านั้น")
            return jsonify({"status": "non_thai"})

        send_line_message(reply_token, "🧘‍♀️ หมอดูกำลังทำนาย รอสักครู่...")
        threading.Thread(target=lambda: push_line_message(user_id, get_fortune(message_text))).start()
        log_usage(user_id, "ใช้งานฟรี", message_text)
    return jsonify({"status": "ok"})

# === แชร์สำเร็จ ===
@app.route("/shared")
def shared():
    referrer = request.args.get("referrer")
    user_id = request.args.get("user_id")
    if not referrer or not user_id:
        return "❌ ต้องแนบ referrer และ user_id"

    if has_shared_before(user_id, referrer):
        return "📌 คุณเคยแชร์ลิงก์นี้ไปแล้ว"

    log_usage(user_id, "ได้สิทธิ์จากการแชร์", "referral", referrer)
    return "✅ รับสิทธิ์เรียบร้อยแล้ว ขอบคุณที่แชร์!"

# === หน้า LIFF ดึง user_id และ redirect ไปยัง /shared
@app.route("/liff-share")
def liff_share():
    return f"""
    <!DOCTYPE html>
    <html lang='th'>
    <head><meta charset='UTF-8'><title>แชร์ลิงก์เชิญเพื่อน</title>
    <script src='https://static.line-scdn.net/liff/edge/2/sdk.js'></script></head>
    <body><h2>กำลังสร้างลิงก์เชิญเพื่อน...</h2><p>โปรดรอสักครู่</p>
    <script>
      async function main() {
        await liff.init({ liffId: '{LIFF_ID}' });
        if (!liff.isLoggedIn()) { liff.login(); return; }
        const profile = await liff.getProfile();
        const userId = profile.userId;
        const urlParams = new URLSearchParams(window.location.search);
        const referrer = urlParams.get('referrer');
        window.location.href = `{PUBLIC_URL}/shared?referrer=${{referrer}}&user_id=${{userId}}`;
      }
      main();
    </script>
    </body></html>
    """

@app.route("/")
def home():
    return "Duangjit AI Ready"

application = app
