from django.utils.timezone import now
from datetime import timedelta
from .models import Task, User
from django.core.mail import send_mail
from django.template.loader import render_to_string

def send_deadline_reminders_logic():
    # Get current time
    current_time = now()

    # Calculate the time window for 24-hour reminders
    reminder_time = current_time + timedelta(hours=24)

    # Fetch tasks with deadlines approaching within the next 24 hours
    tasks = Task.objects.filter(deadline__range=(current_time, reminder_time), status__in=['Not Started', 'In Progress'])

    for task in tasks:
        if task.assigned_to:
            # Send email to the assignee
            context = {
                'user': task.assigned_to,
                'ticket': task,
                'view_ticket_url': f"http://127.0.0.1:8000/tasks/detail/{task.task_id}/",
            }
            email_body = render_to_string('emails/deadline_reminder.html', context)
            send_mail(
                subject=f"Reminder: Task Deadline Approaching ({task.task_id})",
                message='',  # Plain text (empty as we are using HTML)
                from_email='no-reply@yourdomain.com',
                recipient_list=[task.assigned_to.email],
                html_message=email_body,
            )

        if task.assigned_by:
            # Send email to the assignor
            context = {
                'user': task.assigned_by,
                'ticket': task,
                'view_ticket_url': f"http://127.0.0.1:8000/tasks/detail/{task.task_id}/",
            }
            email_body = render_to_string('emails/deadline_reminder.html', context)
            send_mail(
                subject=f"Reminder: Task Deadline Approaching ({task.task_id})",
                message='',  # Plain text (empty as we are using HTML)
                from_email='no-reply@yourdomain.com',
                recipient_list=[task.assigned_by.email],
                html_message=email_body,
            )

def notify_overdue_tasks_logic():
    # Fetch overdue tasks
    overdue_tasks = Task.objects.filter(deadline__lt=now(), status__in=['Not Started', 'In Progress'])

    for task in overdue_tasks:
        if task.assigned_by.email:  # Check if the creator has an email
            # Prepare email context
            context = {
                'task': task,
            }
            email_body = render_to_string('emails/overdue_notification.html', context)
            send_mail(
                f"Overdue Task: {task.task_id}",
                '',  # Empty plain text body
                'no-reply@yourdomain.com',
                [task.assigned_by.email],
                html_message=email_body,
            )
