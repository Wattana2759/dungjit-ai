# Base image Python 3.11 slim
FROM python:3.11-slim

# ติดตั้ง dependencies ของระบบ + Tesseract ภาษาไทย
RUN apt-get update && \
    apt-get install -y \
        tesseract-ocr \
        tesseract-ocr-tha \
        libglib2.0-0 \
        libsm6 \
        libxrender1 \
        libxext6 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ตั้ง working directory
WORKDIR /app

# คัดลอกทุกไฟล์จากโฟลเดอร์โปรเจกต์
COPY . .

# ตั้ง ENV ให้รู้ path ไปยัง Service Account JSON
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/duangjit-ai-808449ecaf0c.json

# ติดตั้ง Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# ให้ Gunicorn รันแอป Flask ที่ชื่อ application ใน app.py
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:application", "--timeout", "90", "--workers", "1"]

