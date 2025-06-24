from flask import Flask, render_template, request, redirect
from datetime import datetime
import os, json
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
from collections import Counter
from werkzeug.utils import secure_filename

# === LOAD ENV ===
load_dotenv()
app = Flask(__name__)

# === CONFIG ===
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SHEET_NAME_USERS = os.getenv("SHEET_NAME_USERS", "Users")
SHEET_NAME_LOGS = os.getenv("SHEET_NAME_LOGS", "Logs")
LIFF_ID = os.getenv("LIFF_ID")

# === อ่าน Service Account JSON จาก path ที่กำหนดใน ENV ===
GOOGLE_JSON_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if not GOOGLE_JSON_PATH or not os.path.exists(GOOGLE_JSON_PATH):
    raise ValueError("❌ ไม่พบไฟล์ Service Account JSON ที่ระบุใน GOOGLE_APPLICATION_CREDENTIALS")

with open(GOOGLE_JSON_PATH, 'r') as f:
    service_account_info = json.load(f)

scope = ["https://www.googleapis.com/auth/spreadsheets"]
credentials = Credentials.from_service_account_info(service_account_info, scopes=scope)
client_gsheet = gspread.authorize(credentials)
sheet_users = client_gsheet.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_USERS)
sheet_logs = client_gsheet.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME_LOGS)

# === Static Path for Uploaded Slips ===
app.config['UPLOAD_FOLDER'] = "static/slips"
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# === Route: LIFF Login ===
@app.route("/liff-login")
def liff_login():
    return render_template("liff_login.html", liff_id=LIFF_ID)

# === Route: Review Slips ===
@app.route("/review-slips")
def review_slips():
    users = sheet_users.get_all_records()
    slips = []
    for u in users:
        if "Slip" in u and u["Slip"]:
            slips.append({"user_id": u["UserID"], "slip": u["Slip"]})
    return render_template("review_slips.html", users=slips)

# === Route: Review Slip Action ===
@app.route("/review-slip-action", methods=["POST"])
def review_slip_action():
    user_id = request.form.get("user_id")
    action = request.form.get("action")
    users = sheet_users.get_all_records()
    for i, user in enumerate(users):
        if user["UserID"] == user_id:
            row = i + 2
            if action == "approve":
                sheet_users.update_cell(row, 4, "อนุมัติ")
            elif action == "reject":
                sheet_users.update_cell(row, 4, "ปฏิเสธ")
            sheet_logs.append_row([str(datetime.now()), user_id, "admin_review", action])
            break
    return redirect("/review-slips")

# === Route: Admin Dashboard ===
@app.route("/admin-dashboard")
def admin_dashboard():
    logs = sheet_logs.get_all_records()
    usage_counter = Counter()
    for log in logs:
        if log.get("action") == "ask":
            date = log.get("timestamp", "").split(" ")[0]
            usage_counter[date] += 1
    chart_data = sorted(usage_counter.items())
    return render_template("admin_dashboard.html", chart_data=chart_data)

# === Route: Upload Slip (LIFF UI) ===
@app.route("/upload-slip", methods=["GET", "POST"])
def upload_slip():
    if request.method == "POST":
        file = request.files.get("file")
        user_id = request.form.get("user_id")
        if file:
            filename = secure_filename(f"{user_id}_{file.filename}")
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)

            users = sheet_users.get_all_records()
            for i, u in enumerate(users):
                if u["UserID"] == user_id:
                    row = i + 2
                    sheet_users.update_cell(row, 5, filename)
                    break
            else:
                sheet_users.append_row([user_id, datetime.now().isoformat(), 0, "", filename])
            return render_template("success.html", user_id=user_id)

    return render_template("upload_slip_liff.html", liff_id=LIFF_ID)

# === Main App Run ===
if __name__ == "__main__":
    app.run(debug=True)

# === For Gunicorn ===
application = app

