from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
def send_ticket_email(subject, template_name, context, recipient_email, cc_emails=None):
    """
    Utility to send HTML email for tickets.
    """
    email_body = render_to_string(template_name, context)
    msg = EmailMultiAlternatives(
        subject=subject,
        body="",  # plain text optional
        from_email='no-reply@yourdomain.com',
        to=[recipient_email],
        cc=list({e.strip().lower() for e in (cc_emails or [])}),
   )
    msg.attach_alternative(email_body, "text/html")
    msg.send(fail_silently=False)