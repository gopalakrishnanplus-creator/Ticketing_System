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


@register.filter(name="user_display_name")
def user_display_name(user, default_value="Unassigned"):
    if not user:
        return default_value
    full_name = ""
    if hasattr(user, "get_full_name"):
        full_name = (user.get_full_name() or "").strip()
    if full_name:
        return full_name
    username = getattr(user, "username", "")
    return username or default_value


@register.filter(name="user_initial")
def user_initial(user, default_value="U"):
    display_name = user_display_name(user, "")
    if display_name:
        return display_name[:1].upper()
    return default_value


@register.filter(name="user_department_name")
def user_department_name(user, default_value="Unassigned"):
    if not user:
        return default_value
    profile = getattr(user, "userprofile", None)
    department = getattr(profile, "department", None)
    name = getattr(department, "name", "")
    return name or default_value
