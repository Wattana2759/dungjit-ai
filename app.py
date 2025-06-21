from flask import Flask, request, jsonify
import os
import requests
from dotenv import load_dotenv
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# โหลด ENV
load_dotenv()
app = Flask(__name__)

# LINE API
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# OpenAI API
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Google Sheets
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME_USERS = os.getenv("SHEET_NAME_USERS", "Users")

# Google Auth (Service Account)
google_creds = {
    "type": os.getenv("GOOGLE_TYPE"),
    "project_id": os.getenv("GOOGLE_PROJECT_ID"),
    "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
    "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
    "auth_uri": os.getenv("GOOGLE_AUTH_URI"),
    "token_uri": os.getenv("GOOGLE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("GOOGLE_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL")
}

# LINE: ตอบกลับข้อความ
def send_reply(reply_token, message):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": message}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=data)

# OpenAI: สร้างข้อความดูดวง
def get_fortune(prompt):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "คุณคือหมอดูไทยโบราณ พูดจาสุภาพและให้คำทำนายอย่างจริงใจ"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content.strip()

# Google Sheets: บันทึกผู้ใช้
def log_user(user_id):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
    client_sheet = gspread.authorize(creds)
    sheet = client_sheet.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
    all_user_ids = sheet.col_values(1)

    if user_id not in all_user_ids:
        sheet.append_row([user_id])

# Webhook หลัก
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_json()
    print("🛜 Webhook Received:", body)

    for event in body.get("events", []):
        if event["type"] == "message" and event["message"]["type"] == "text":
            user_id = event["source"]["userId"]
            text = event["message"]["text"]
            reply_token = event["replyToken"]

            log_user(user_id)

            if "ความรัก" in text:
                prompt = "ดูดวงความรักวันนี้"
            elif "โชคลาภ" in text:
                prompt = "ดูดวงโชคลาภวันนี้"
            else:
                prompt = "ดูดวงวันนี้"

            reply_text = get_fortune(prompt)
            send_reply(reply_token, reply_text)

    return jsonify({"status": "ok"})

# หน้า default
@app.route("/", methods=["GET"])
def home():
    return "🔮 ดวงจิต AI - LINE Bot ทำงานปกติ"

# รัน local (optional)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

