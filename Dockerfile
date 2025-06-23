# Dockerfile
FROM python:3.13-slim

# ติดตั้ง system dependencies
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-tha libglib2.0-0 libsm6 libxrender1 libxext6 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# สร้าง working directory
WORKDIR /app

# คัดลอกโค้ดทั้งหมด
COPY . .

# ตั้ง ENV สำหรับ GOOGLE_APPLICATION_CREDENTIALS
ENV GOOGLE_APPLICATION_CREDENTIALS="/app/duangjit-sa.json"

# ติดตั้ง dependencies
RUN pip install --no-cache-dir -r requirements.txt

# รัน Flask app ด้วย gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:application"]

