# ✅ ใช้ base image เป็น python 3.11 แบบ slim (ประหยัด)
FROM python:3.11-slim

# ✅ ติดตั้ง tesseract + ภาษาไทย + dependency ภาพ
RUN apt-get update && \
    apt-get install -y \
        tesseract-ocr \
        tesseract-ocr-tha \
        libglib2.0-0 libsm6 libxrender1 libxext6 && \
    apt-get clean

# ✅ ตั้งค่าที่เก็บโค้ดใน container
WORKDIR /app

# ✅ คัดลอกไฟล์ทั้งหมดจากเครื่อง → เข้า container
COPY . .

# ✅ ติดตั้งไลบรารี Python
RUN pip install --no-cache-dir -r requirements.txt

# ✅ รัน Flask ด้วย gunicorn (port 8000)
CMD ["gunicorn", "app:application", "--bind", "0.0.0.0:8000"]
