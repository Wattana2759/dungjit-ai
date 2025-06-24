from celery import Celery
from app import extract_payment_info, add_or_update_user, push_line_message, log_usage
from PIL import Image
import pytesseract
import cv2

celery = Celery("tasks", broker="redis://localhost:6379/0")

@celery.task
def process_slip_async(user_id, user_name, filepath):
    # Resize
    img = cv2.imread(filepath)
    h, w = img.shape[:2]
    if w > 1000:
        img = cv2.resize(img, (1000, int(h * 1000 / w)))
        cv2.imwrite(filepath, img)

    # OCR
    ocr_text = pytesseract.image_to_string(Image.open(filepath), lang="eng+tha")
    info = extract_payment_info(ocr_text)
    amount_paid = int(float(info["amount"])) if info["amount"] else 0
    add_or_update_user(user_id, user_name, amount_paid, os.path.basename(filepath))
    push_line_message(user_id, f"📥 ได้รับสลิปแล้ว เพิ่มสิทธิ์ {amount_paid} ครั้งเรียบร้อย ✅")
    log_usage(user_id, "แนบสลิป", f"OCR: {info}")
