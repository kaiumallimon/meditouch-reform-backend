from datetime import datetime, timezone
import uuid
import re

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def generate_uuid() -> str:
    return str(uuid.uuid4())

def generate_invoice_number(prefix: str = "INV") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    unique_suffix = uuid.uuid4().hex[:6].upper()
    return f"{prefix}-{timestamp}-{unique_suffix}"

def calculate_fee_breakdown(doctor_fee: float, platform_fee_percent: float) -> tuple[float, float, float]:
    platform_fee = round(doctor_fee * (platform_fee_percent / 100.0), 2)
    total_amount = round(doctor_fee + platform_fee, 2)
    return doctor_fee, platform_fee, total_amount

def sanitize_phone_number(phone: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", phone)
    if cleaned.startswith("880"):
        cleaned = "+" + cleaned
    elif cleaned.startswith("01"):
        cleaned = "+880" + cleaned[1:]
    return cleaned
