FROM python:3.11-slim

# ติดตั้ง system dependencies ที่จำเป็นสำหรับ OCR และ OpenCV
RUN apt-get update && \
    apt-get install -y \
        tesseract-ocr \
        tesseract-ocr-tha \
        libglib2.0-0 \
        libsm6 \
        libxrender1 \
        libxext6 \
        libgl1 \
        && apt-get clean && rm -rf /var/lib/apt/lists/*

# ตั้ง working directory
WORKDIR /app

# คัดลอกไฟล์ทั้งหมด
COPY . .

# ติดตั้ง Python dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir --extra-index-url https://pypi.org/simple \
    opencv-python-headless==4.8.0.76 \
    -r requirements.txt

# เริ่มรันแอป Flask ด้วย Gunicorn
CMD ["gunicorn", "app:application", "--bind", "0.0.0.0:10000"]

