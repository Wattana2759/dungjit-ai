# ใช้ base image Python 3.13 ที่เบา
FROM python:3.13-slim

# ติดตั้ง dependencies ของระบบ + Tesseract ภาษาไทย
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-tha libglib2.0-0 libsm6 libxrender1 libxext6 && \
    tesseract --list-langs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# กำหนดโฟลเดอร์ทำงาน
WORKDIR /app

# คัดลอกไฟล์ทั้งหมดเข้า container
COPY . .

# ตั้งค่าตำแหน่งไฟล์ Service Account สำหรับ Google Sheets API
ENV GOOGLE_APPLICATION_CREDENTIALS="/app/duangjit-ai-808449ecaf0c.json"

# ติดตั้ง Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# ใช้ Gunicorn เพื่อรัน Flask app (port 10000 สำหรับ Render)
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:application", "--timeout", "90", "--workers", "1"]

