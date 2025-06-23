# Dockerfile
FROM python:3.13-slim

# ติดตั้ง system dependencies รวมถึง tesseract และภาษาไทย
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-tha libglib2.0-0 libsm6 libxrender1 libxext6 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# สร้าง working directory
WORKDIR /app

# คัดลอกโค้ดทั้งหมดลงใน container รวมถึงไฟล์ JSON Key
COPY . .

# ติดตั้ง dependencies
RUN pip install --no-cache-dir -r requirements.txt

# ตั้ง ENV ให้รู้จัก Google Credentials (หากคุณใช้ Render สามารถ override ได้บน Dashboard)
ENV GOOGLE_APPLICATION_CREDENTIALS="/app/duangjit-ai-808449ecaf0c.json"

# รันแอป Flask ด้วย gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:app"]

