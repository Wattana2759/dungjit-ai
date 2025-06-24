from celery import Celery
from app import extract_payment_info, add_or_update_user, push_line_message, log_usage
from PIL import Image
import pytesseract
import cv2
import os

celery = Celery("tasks", broker="redis://localhost:6379/0")

@celery.task
def process_slip_async(user_id, user_name, filepath):
    try:
        # ✅ Resize image if too large
        img = cv2.imread(filepath)
        if img is None:
            raise ValueError("ไม่สามารถอ่านภาพจากไฟล์ได้")

        h, w = img.shape[:2]
        if w > 1000:
            new_w = 1000
            new_h = int(h * (1000 / w))
            img = cv2.resize(img, (new_w, new_h))
            cv2.imwrite(filepath, img)

        # ✅ OCR with Tesseract
        ocr_text = pytesseract.image_to_string(Image.open(filepath), lang="eng+tha")

        # ✅ Extract payment info (name / amount)
        info = extract_payment_info(ocr_text)
        if not info["amount"]:
            push_line_message(user_id, "❌ ไม่พบจำนวนเงินในสลิป กรุณาแนบใหม่อีกครั้ง")
            log_usage(user_id, "แนบสลิปล้มเหลว", f"OCR: {ocr_text}")
            return

        amount_paid = int(float(info["amount"]))
        add_or_update_user(user_id, user_name, amount_paid, os.path.basename(filepath))

        # ✅ Notify user
        push_line_message(user_id, f"📥 ได้รับสลิปแล้ว เพิ่มสิทธิ์ {amount_paid} ครั้งเรียบร้อย ✅")
        log_usage(user_id, "แนบสลิป", f"OCR: {info}")

    except Exception as e:
        push_line_message(user_id, f"❌ ระบบขัดข้อง: {str(e)}")
        log_usage(user_id, "แนบสลิปล้มเหลว", f"Error: {str(e)}")

