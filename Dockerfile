# Dockerfile
FROM python:3.13-slim

# ติดตั้ง dependencies ของระบบและ tesseract
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-tha libglib2.0-0 libsm6 libxrender1 libxext6 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# กำหนด Working Directory
WORKDIR /app

# คัดลอกไฟล์ทั้งหมด
COPY . .

# ตั้งค่าตำแหน่ง service account json
ENV GOOGLE_APPLICATION_CREDENTIALS="/app/duangjit-sa.json"

# ติดตั้ง Python packages
RUN pip install --no-cache-dir -r requirements.txt

# รันแอป Flask ด้วย gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:application"]

