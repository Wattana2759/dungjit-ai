# Dockerfile
FROM python:3.13-slim

# ติดตั้ง system dependencies รวมถึง tesseract และภาษาไทย
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-tha libglib2.0-0 libsm6 libxrender1 libxext6 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# สร้าง working directory
WORKDIR /app

# คัดลอกโค้ดทั้งหมดลงใน container
COPY . .

# ติดตั้ง dependencies จาก requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# รันแอป Flask ด้วย gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:10000", "app:application"]

