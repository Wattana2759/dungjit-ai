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

# === โหลด ENV ===
load_dotenv()
app = Flask(__name__)

# === ENV & Setup ===
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LIFF_ID = os.getenv("LIFF_ID")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:5000")
client = OpenAI(api_key=OPENAI_API_KEY)
engine = create_engine('sqlite:///db.sqlite')
Session = sessionmaker(bind=engine)
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")

# === Basic Auth ===
def require_basic_auth():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
        return Response("กรุณาเข้าสู่ระบบ", 401, {"WWW-Authenticate": "Basic realm='Admin Access'"})

# === ตรวจสอบเซิร์ฟเวอร์ทำงาน
@app.route("/", methods=["GET"])
def index():
    return "✅ Duangjit AI Webhook Server is Running", 200

# === Webhook จาก LINE
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    if not data or "events" not in data:
        return jsonify(status="ignored"), 200

    for event in data["events"]:
        reply_token = event["replyToken"]
        user_id = event["source"]["userId"]
        if event.get("deliveryContext", {}).get("isRedelivery"):
            continue

        session = Session()
        user = session.get(User, user_id)

        if event["type"] == "follow":
            push_line_message(user_id, "🙏 ยินดีต้อนรับสู่ ดวงจิต AI!")
            return jsonify(status="followed"), 200

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

    return jsonify(status="ok"), 200

# === ส่งข้อความ
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
                "url": f"{PUBLIC_URL}/static/qr_promptpay.png",
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
                "url": f"{PUBLIC_URL}/static/banner.jpg",
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
                            "uri": f"{PUBLIC_URL}/upload-slip-liff"
                        }
                    }
                ]
            }
        }
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json={"to": user_id, "messages": [flex_message]})

# === Fortune with GPT
def get_fortune(message):
    prompt = f"""คุณคือหมอดูไทยโบราณ ผู้มีญาณหยั่งรู้ พูดจาเคร่งขรึม สุภาพ ตอบคำถามเรื่องดวงชะตา ความรัก การเงิน และความฝัน

ผู้ใช้ถาม: "{message}"
คำตอบของหมอดู:"""
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("❌ OpenAI Error:", e)
        return "ขออภัย ระบบหมอดู AI ไม่สามารถให้คำตอบได้ในขณะนี้ กำลังปรับปรุงระบ

