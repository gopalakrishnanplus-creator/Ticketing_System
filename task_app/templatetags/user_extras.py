from django import template
from django.contrib.auth.models import User

register = template.Library()

@register.filter(name="get_user_by_email")
def get_user_by_email(value, email_arg=None):
    """
    Usage (both work):
      {{ email|get_user_by_email }}              -> value is the email string
      {{ users|get_user_by_email:email }}        -> ignores 'users', uses email arg
    Returns a User instance or None.
    """
    email = (email_arg or value or "").strip().lower()
    if not email:
        return None
    try:
        return User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        return None
