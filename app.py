from flask import Flask, request, jsonify, render_template, Response
from openai import OpenAI
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image
import pytesseract
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db_setup import User, Log
import re

load_dotenv()
app = Flask(__name__)

# === ENV & Setup ===
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LIFF_ID = os.getenv("LIFF_ID")
client = OpenAI(api_key=OPENAI_API_KEY)
engine = create_engine('sqlite:///db.sqlite')
Session = sessionmaker(bind=engine)
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")

def require_basic_auth():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
        return Response("กรุณาเข้าสู่ระบบ", 401, {"WWW-Authenticate": "Basic realm='Admin Access'"})

def get_ngrok_public_url():
    try:
        tunnels = requests.get("http://127.0.0.1:4040/api/tunnels").json()
        for tunnel in tunnels['tunnels']:
            if tunnel['proto'] == 'https':
                return tunnel['public_url']
    except Exception as e:
        print("❌ ไม่สามารถดึง ngrok URL ได้:", e)
        return "http://localhost:5000"

public_url = os.getenv("PUBLIC_URL", "http://localhost:5000")
print("Public URL:", public_url)

# === Messaging ===
def send_line_message(reply_token, text):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    body = {"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=body)

def push_line_message(user_id, text):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    body = {"to": user_id, "messages": [{"type": "text", "text": text}]}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body)

def send_payment_request(user_id):
    flex_qr = {
        "type": "flex",
        "altText": "กรุณาชำระเงินก่อนแนบสลิป",
        "contents": {
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": f"{public_url}/static/qr_promptpay.png",
                "size": "full",
                "aspectRatio": "1:1",
                "aspectMode": "cover"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "📌 สแกนจ่ายผ่าน PromptPay", "weight": "bold", "size": "md"},
                    {"type": "text", "text": "บัญชี: นาย วัฒนา จันดาหาร", "size": "sm", "wrap": True},
                    {"type": "text", "text": "คำถามละ 1 บาท — แนบสลิปภายหลัง", "size": "sm", "wrap": True}
                ]
            }
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
            "hero": {
                "type": "image",
                "url": f"{public_url}/static/banner.jpg",
                "size": "full",
                "aspectRatio": "16:9",
                "aspectMode": "cover"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "แนบสลิปเพื่อรับสิทธิ์ใช้งานดวงจิต หมอดู AI",
                        "weight": "bold",
                        "size": "md",
                        "wrap": True
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "color": "#06c755",
                        "action": {
                            "type": "uri",
                            "label": "แนบสลิปตอนนี้",
                            "uri": f"{public_url}/upload-slip-liff"
                        }
                    }
                ]
            }
        }
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json={"to": user_id, "messages": [flex_message]})

# === Fortune ===
def get_fortune(message):
    prompt = f"""คุณคือหมอดูไทยโบราณ ผู้มีญาณหยั่งรู้ พูดจาเคร่งขรึม สุภาพ ตอบคำถามเรื่องดวงชะตา ความรัก การเงิน และความฝัน

ผู้ใช้ถาม: "{message}"
คำตอบของหมอดู:"""
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ OpenAI Error:", e)
        return "ขออภัย ระบบหมอดู AI ไม่สามารถให้คำตอบได้ในขณะนี้ กำลังปรับปรุงระบบ"

# === OCR จากสลิป ===
def extract_payment_info(text):
    name = re.search(r'(ชื่อ[^\n\r]+)', text)
    amount = re.search(r'(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(บาท|฿)?', text)
    return {
        'amount': amount.group(1).replace(',', '') if amount else None,
        'name': name.group(1).strip() if name else None
    }

# === Log การใช้งาน ===
def log_usage(line_id, action, detail):
    try:
        session = Session()
        session.add(Log(line_id=line_id, action=action, detail=detail))
        session.commit()
    except Exception as e:
        print("❌ Log Error:", e)

# === Webhook ===
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

        session = Session()
        user = session.get(User, user_id)

        if event["type"] == "follow":
            push_line_message(user_id, "🙏 ยินดีต้อนรับสู่ ดวงจิต AI!")
            return jsonify(status="followed")

        if event["type"] == "message":
            try:
                message_text = event["message"]["text"]
            except KeyError:
                send_line_message(reply_token, "ระบบรองรับเฉพาะข้อความค่ะ")
                continue

            if message_text.strip().lower() == "/ดูสิทธิ์":
                if not user:
                    send_line_message(reply_token, "คุณยังไม่มีสิทธิ์ใช้งาน")
                else:
                    send_line_message(reply_token, f"คุณใช้ไปแล้ว {user.usage or 0} ครั้ง / {user.paid_quota or 0} ครั้ง")
                continue

            if not user or user.paid_quota is None or user.paid_quota <= 0:
                push_line_message(user_id, "💸 กรุณาชำระเงิน (1 บาท = 1 คำถาม)")
                send_payment_request(user_id)
                send_flex_upload_link(user_id)
                continue

            if user.usage >= user.paid_quota:
                push_line_message(user_id, "❌ คุณใช้สิทธิ์ครบแล้ว กรุณาแนบสลิปเพื่อเติมคำถาม")
                send_flex_upload_link(user_id)
                continue

            reply = get_fortune(message_text)
            send_line_message(reply_token, reply)
            user.usage += 1
            session.commit()

    return jsonify(status="ok")

# === Upload Slip ===
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

        session = Session()
        user = session.get(User, user_id)
        if user:
            user.paid_quota += amount_paid
            user.slip_file = filename
            user.last_uploaded = datetime.now()
            if user_name:
                user.name = user_name
        else:
            user = User(id=user_id, name=user_name, usage=0, paid_quota=amount_paid, slip_file=filename, last_uploaded=datetime.now())
            session.add(user)

        session.commit()
        push_line_message(user_id, f"📥 ได้รับสลิปแล้ว เพิ่มสิทธิ์ {amount_paid} ครั้งเรียบร้อย ✅")
        log_usage(user_id, "แนบสลิป", f"OCR: {info}")
        return render_template("success.html", user_id=user_id)

    return render_template("upload_form.html")

@app.route("/upload-slip-liff")
def upload_slip_liff():
    return render_template("upload_slip_liff.html", liff_id=LIFF_ID)

# === Admin Dashboard ===
@app.route("/admin")
def admin_dashboard():
    auth = require_basic_auth()
    if auth:
        return auth
    session = Session()
    return render_template("admin.html", users=session.query(User).all(), logs=session.query(Log).order_by(Log.timestamp.desc()).limit(50).all())

@app.route("/review-slips")
def review_slips():
    auth = require_basic_auth()
    if auth:
        return auth
    session = Session()
    users_with_slip = session.query(User).filter(User.slip_file != None).all()
    return render_template("review_slips.html", users=users_with_slip)

@app.route("/review-slip-action", methods=["POST"])
def review_slip_action():
    auth = require_basic_auth()
    if auth:
        return auth
    user_id = request.form.get("user_id")
    action = request.form.get("action")
    session = Session()
    user = session.get(User, user_id)

    if not user:
        return "ไม่พบผู้ใช้", 404

    if action == "approve":
        user.paid_quota += 5
        push_line_message(user_id, "✅ สลิปของคุณได้รับการอนุมัติแล้ว")
        log_usage(user_id, "admin-approve", "อนุมัติสลิป")
    elif action == "reject":
        user.slip_file = None
        push_line_message(user_id, "❌ สลิปของคุณถูกปฏิเสธ กรุณาแนบใหม่")
        log_usage(user_id, "admin-reject", "ปฏิเสธสลิป")

    session.commit()
    return render_template("success.html", user_id=user_id)

@app.route("/success")
def success_page():
    return render_template("success.html", user_id=request.args.get("user_id", "ไม่ทราบ"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)



