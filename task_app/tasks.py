from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.timezone import now

from .models import Task, User


def _task_base_url():
    return getattr(settings, "CLIENT_TICKETS_BASE_URL", "https://support.inditech.co.in").rstrip("/")


def send_deadline_reminders_logic():
    current_time = now()
    reminder_time = current_time + timedelta(hours=24)
    tasks = Task.objects.filter(deadline__range=(current_time, reminder_time), status__in=['Not Started', 'In Progress'])

    for task in tasks:
        if task.assigned_to:
            context = {
                'user': task.assigned_to,
                'ticket': task,
                'view_ticket_url': f"{_task_base_url()}/tasks/detail/{task.task_id}/",
            }
            email_body = render_to_string('emails/deadline_reminder.html', context)
            send_mail(
                subject=f"Reminder: Task Deadline Approaching ({task.task_id})",
                message='',
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@yourdomain.com"),
                recipient_list=[task.assigned_to.email],
                html_message=email_body,
            )

        if task.assigned_by:
            context = {
                'user': task.assigned_by,
                'ticket': task,
                'view_ticket_url': f"{_task_base_url()}/tasks/detail/{task.task_id}/",
            }
            email_body = render_to_string('emails/deadline_reminder.html', context)
            send_mail(
                subject=f"Reminder: Task Deadline Approaching ({task.task_id})",
                message='',
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@yourdomain.com"),
                recipient_list=[task.assigned_by.email],
                html_message=email_body,
            )


def notify_overdue_tasks_logic():
    overdue_tasks = Task.objects.filter(deadline__lt=now(), status__in=['Not Started', 'In Progress'])

    for task in overdue_tasks:
        if task.assigned_by and task.assigned_by.email:
            context = {
                'manager': task.assigned_by,
                'task': task,
                'ticket': task,
                'view_ticket_url': f"{_task_base_url()}/tasks/detail/{task.task_id}/",
            }
            email_body = render_to_string('emails/overdue_notification.html', context)
            send_mail(
                f"Overdue Task: {task.task_id}",
                '',
                getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@yourdomain.com"),
                [task.assigned_by.email],
                html_message=email_body,
            )
