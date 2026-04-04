import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives


MAX_INTERNAL_ATTACHMENTS_PER_TICKET = 10
MAX_INTERNAL_ATTACHMENT_SIZE = 5 * 1024 * 1024


def validate_internal_attachment(upload):
    if upload.size > MAX_INTERNAL_ATTACHMENT_SIZE:
        raise ValidationError(f"{upload.name}: file size exceeds 5 MB.")


def validate_internal_attachment_batch(files, existing_count=0):
    attachments = [file for file in (files or []) if file]
    if existing_count + len(attachments) > MAX_INTERNAL_ATTACHMENTS_PER_TICKET:
        raise ValidationError("A ticket can have at most 10 attachments in total.")
    for attachment in attachments:
        validate_internal_attachment(attachment)
    return attachments


def send_ticket_email(subject, template_name, context, recipient_email, cc_emails=None):
    """
    Utility to send HTML email for tickets.
    """
    email_body = render_to_string(template_name, context)
    msg = EmailMultiAlternatives(
        subject=subject,
        body="",  # plain text optional
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@yourdomain.com"),
        to=[recipient_email],
        cc=list({e.strip().lower() for e in (cc_emails or [])}),
   )
    msg.attach_alternative(email_body, "text/html")
    msg.send(fail_silently=False)
