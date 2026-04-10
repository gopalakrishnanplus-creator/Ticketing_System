import os
import re

from django.conf import settings
from django.core.exceptions import ValidationError


ALLOWED_ATTACHMENT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf", ".mp4", ".heic", ".hevc"}
MAX_ATTACHMENTS_PER_TICKET = 5
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024


def normalize_email(value):
    return (value or "").strip().lower()


def normalize_phone_number(value):
    raw_value = (value or "").strip()
    if not raw_value:
        return ""
    if raw_value.startswith("+"):
        return "+" + re.sub(r"\D", "", raw_value[1:])
    return re.sub(r"\D", "", raw_value)


def validate_upload(upload):
    extension = os.path.splitext(upload.name)[1].lower()
    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValidationError(
            f"{upload.name}: unsupported file type. Allowed formats are jpg, jpeg, png, pdf, mp4, heic, hevc."
        )
    if upload.size > MAX_ATTACHMENT_SIZE:
        raise ValidationError(f"{upload.name}: file size exceeds 10 MB.")


def validate_attachment_batch(files, existing_count=0):
    attachments = [file for file in (files or []) if file]
    if existing_count + len(attachments) > MAX_ATTACHMENTS_PER_TICKET:
        raise ValidationError("A ticket can have at most 5 attachments in total.")
    for attachment in attachments:
        validate_upload(attachment)
    return attachments


def get_base_url():
    return getattr(settings, "CLIENT_TICKETS_BASE_URL", "https://support.inditech.co.in").rstrip("/")


def build_absolute_link(path):
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{get_base_url()}{path}"


def priority_color(priority):
    colors = {
        "low": "#2e7d32",
        "medium": "#ef6c00",
        "high": "#d84315",
        "urgent": "#c62828",
    }
    return colors.get((priority or "").lower(), "#455a64")
