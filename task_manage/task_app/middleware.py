from .models import UserProfile


class EnsureUserProfileMiddleware:
    """Create a default profile for authenticated users that are missing one."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if getattr(user, "is_authenticated", False):
            UserProfile.objects.get_or_create(
                user=user,
                defaults={"category": "Non-Management"},
            )
        return self.get_response(request)
