from flask import Flask, request, jsonify, render_template, Response
import os
from dotenv import load_dotenv
import requests
from openai import OpenAI
from PIL import Image
import pytesseract
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db_setup import User, Log
import re
import gspread
from google.oauth2.service_account import Credentials
import base64

load_dotenv()

app = Flask(__name__)

# === ENV & SETUP ===
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME_USERS = os.getenv("SHEET_NAME_USERS")
SHEET_NAME_LOGS = os.getenv("SHEET_NAME_LOGS")
LIFF_ID = os.getenv("LIFF_ID")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:5000")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "1234")

# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# === DATABASE ===
engine = create_engine('sqlite:///db.sqlite')
Session = sessionmaker(bind=engine)

# === GOOGLE SHEET CREDENTIAL ===
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_file(
    '/etc/secrets/GOOGLE_CREDS_JSON', scopes=SCOPES
)
gc = gspread.authorize(creds)
users_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
logs_sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === BASIC AUTH ===
def require_basic_auth():
    auth = request.authorization
    if not auth or auth.username != ADMIN_USER or auth.password != ADMIN_PASS:
        return Response("กรุณาเข้าสู่ระบบ", 401, {"WWW-Authenticate": "Basic realm='Login Required'"})

# === ROUTES ===
@app.route('/')
def index():
    return "🧠 ดวงจิต AI พร้อมใช้งาน"

@app.route('/admin')
def admin_dashboard():
    auth = require_basic_auth()
    if auth: return auth
    return render_template("admin.html")

@app.route('/upload-slip', methods=['GET', 'POST'])
def upload_slip():
    if request.method == 'POST':
        image = request.files['slip']
        if image:
            img = Image.open(image.stream)
            text = pytesseract.image_to_string(img, lang='tha+eng')

            amount_match = re.search(r'(\d+[,.]?\d*)\s*(บาท|THB)', text)
            name_match = re.search(r'(นาย|นางสาว|บริษัท|คุณ)\s?\S+', text)

            amount = amount_match.group(1) if amount_match else "ไม่พบจำนวนเงิน"
            name = name_match.group(0) if name_match else "ไม่พบชื่อ"

            return jsonify({"name": name, "amount": amount})
        return "ไม่พบรูปภาพ", 400
    return render_template("upload_slip.html", liff_id=LIFF_ID)

# === WEBHOOK ===
@app.route("/webhook", methods=['POST'])
def webhook():
    payload = request.get_json()
    # จะเพิ่ม logic การรับข้อความ LINE + สื่อสารกับ OpenAI หรือระบบดวงได้ที่นี่
    return jsonify({"status": "ok"})

# === DEBUG OCR แบบ Base64 (optional สำหรับ POST image via JS) ===
@app.route('/ocr', methods=['POST'])
def ocr_base64():
    data = request.get_json()
    base64_img = data.get('image_base64')
    if base64_img:
        img_data = base64.b64decode(base64_img.split(',')[-1])
        img = Image.open(io.BytesIO(img_data))
        text = pytesseract.image_to_string(img, lang='tha+eng')
        return jsonify({"text": text})
    return jsonify({"error": "ไม่พบภาพ base64"}), 400

# === RUN ===
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')

