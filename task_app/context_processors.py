# task_app/context_processors.py

from .models import UserProfile

def user_category(request):
    ticket_mode = request.session.get('ticket_ui_mode', 'internal')
    if ticket_mode not in {'internal', 'external'}:
        ticket_mode = 'internal'

    if request.user.is_authenticated:
        user_profile = UserProfile.objects.filter(user=request.user).first()
        return {
            'user_category': user_profile.category if user_profile else None,
            'current_ticket_mode': ticket_mode,
            'is_external_ticket_mode': ticket_mode == 'external',
        }
    return {
        'current_ticket_mode': ticket_mode,
        'is_external_ticket_mode': ticket_mode == 'external',
    }
