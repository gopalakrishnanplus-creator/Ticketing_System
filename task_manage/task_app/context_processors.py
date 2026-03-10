# task_app/context_processors.py

from .models import UserProfile

def user_category(request):
    if request.user.is_authenticated:
        user_profile = UserProfile.objects.filter(user=request.user).first()
        return {'user_category': user_profile.category if user_profile else None}
    return {}
