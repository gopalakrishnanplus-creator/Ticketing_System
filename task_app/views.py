from django.shortcuts import render, redirect, get_object_or_404
from .models import Task, UserProfile, Department, TaskChat
from django.contrib.auth.decorators import login_required
from .forms import TaskForm, TaskChatForm
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Q,F
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.http import HttpResponse
from .models import ActivityLog
import csv
import pandas as pd
from django.db.models import Count
from .forms import TaskStatusUpdateForm
from django.core.mail import send_mail
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.timezone import now
from .tasks import send_deadline_reminders_logic, notify_overdue_tasks_logic
from django.contrib import messages
from datetime import date
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse
import logging
import json

from client_tickets.forms import ClientTicketForm
from client_tickets.models import ClientTicket, ClientTicketType, ClientTicketUpdate
from client_tickets.services import create_ticket_update, notify_ticket_created, upsert_client_contact

logger = logging.getLogger(__name__)

TICKET_MODE_INTERNAL = 'internal'
TICKET_MODE_EXTERNAL = 'external'
TICKET_MODE_CHOICES = {TICKET_MODE_INTERNAL, TICKET_MODE_EXTERNAL}

def send_email_notification(subject, template_name, context, recipient_email, cc_emails=None):
    """Utility function to send email notifications (with CC)."""
    email_body = render_to_string(template_name, context)
    msg = EmailMultiAlternatives(
        subject=subject,
        body='',
        from_email='no-reply@yourdomain.com',
        to=[recipient_email],
        cc=list({e.strip().lower() for e in (cc_emails or [])}),
    )
    msg.attach_alternative(email_body, "text/html")
    msg.send(fail_silently=False)
def _norm_emails(iterable):
    return sorted(list({(e or "").strip().lower() for e in (iterable or []) if (e or "").strip()}))


def get_ticket_ui_mode(request):
    mode = request.session.get('ticket_ui_mode', TICKET_MODE_INTERNAL)
    if mode not in TICKET_MODE_CHOICES:
        mode = TICKET_MODE_INTERNAL
    return mode


def _safe_ticket_redirect_target(request, fallback='assigned_to_me'):
    redirect_to = request.GET.get('next') or request.POST.get('next')
    if redirect_to and url_has_allowed_host_and_scheme(
        redirect_to,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect_to
    return reverse(fallback)


def _query_string_without_page(request):
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


def _paginate_records(request, queryset, per_page=10):
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get('page') or 1)


def _apply_internal_filters(queryset, request):
    today = date.today()
    search = (request.GET.get('q') or '').strip()
    quick_filter = (request.GET.get('quick') or '').strip()
    priority = (request.GET.get('priority') or '').strip()
    status = (request.GET.get('status') or '').strip()
    department = (request.GET.get('department') or '').strip()
    deadline = (request.GET.get('deadline') or '').strip()

    if search:
        queryset = queryset.filter(
            Q(task_id__icontains=search) |
            Q(subject__icontains=search) |
            Q(request_details__icontains=search) |
            Q(assigned_by__username__icontains=search) |
            Q(assigned_by__first_name__icontains=search) |
            Q(assigned_by__last_name__icontains=search) |
            Q(assigned_to__username__icontains=search) |
            Q(assigned_to__first_name__icontains=search) |
            Q(assigned_to__last_name__icontains=search)
        )
    if quick_filter == 'this_week':
        queryset = queryset.filter(deadline__gte=today, deadline__lte=today + timedelta(days=7))
    elif quick_filter == 'next_24_hours':
        queryset = queryset.filter(deadline__gte=today, deadline__lte=today + timedelta(days=1))
    elif quick_filter == 'overdue':
        queryset = queryset.filter(deadline__lt=today).exclude(status__in=['Completed', 'Cancelled'])
    if priority:
        queryset = queryset.filter(priority=priority)
    if status:
        queryset = queryset.filter(status=status)
    if department:
        queryset = queryset.filter(department__name=department)
    if deadline:
        parsed_deadline = parse_date(deadline)
        if parsed_deadline:
            queryset = queryset.filter(deadline=parsed_deadline)

    return queryset, {
        'search': search,
        'quick': quick_filter,
        'priority': priority,
        'status': status,
        'department': department,
        'deadline': deadline,
    }


def _apply_external_filters(queryset, request):
    search = (request.GET.get('q') or '').strip()
    department = (request.GET.get('department') or '').strip()
    user_type = (request.GET.get('user_type') or '').strip()
    source_system = (request.GET.get('source_system') or '').strip()
    priority = (request.GET.get('priority') or '').strip()
    status = (request.GET.get('status') or '').strip()

    if search:
        queryset = queryset.filter(
            Q(ticket_number__icontains=search) |
            Q(title__icontains=search) |
            Q(description__icontains=search) |
            Q(requester_name__icontains=search) |
            Q(requester_email__icontains=search)
        )
    if department:
        queryset = queryset.filter(department__name=department)
    if user_type:
        queryset = queryset.filter(user_type=user_type)
    if source_system:
        queryset = queryset.filter(source_system=source_system)
    if priority:
        queryset = queryset.filter(priority=priority)
    if status:
        queryset = queryset.filter(status=status)

    return queryset, {
        'search': search,
        'department': department,
        'user_type': user_type,
        'source_system': source_system,
        'priority': priority,
        'status': status,
    }


def _internal_summary(queryset):
    today = date.today()
    return {
        'total': queryset.count(),
        'open': queryset.exclude(status__in=['Completed', 'Cancelled']).count(),
        'overdue': queryset.filter(deadline__lt=today).exclude(status__in=['Completed', 'Cancelled']).count(),
        'urgent': queryset.filter(priority='urgent').count(),
    }


def _external_summary(queryset):
    return {
        'total': queryset.count(),
        'open': queryset.exclude(
            status__in=[ClientTicket.STATUS_CLOSED, ClientTicket.STATUS_AUTO_CLOSED, ClientTicket.STATUS_CANCELLED]
        ).count(),
        'waiting': queryset.filter(
            status__in=[ClientTicket.STATUS_WAITING_FOR_CLIENT, ClientTicket.STATUS_WAITING_FOR_INDITECH]
        ).count(),
        'urgent': queryset.filter(priority=ClientTicket.PRIORITY_URGENT).count(),
    }


def _internal_assigned_to_queryset(user, user_profile):
    queryset = Task.objects.select_related('department', 'assigned_by', 'assigned_to')
    if user_profile.category == 'Task Management System Manager':
        return queryset.all()
    if user_profile.category == 'Departmental Manager' and user_profile.department_id:
        department = user_profile.department
        return queryset.filter(
            Q(assigned_to=user) |
            Q(assigned_to__userprofile__department=department) |
            Q(assigned_by__userprofile__department=department) |
            Q(department=department)
        ).distinct()
    return queryset.filter(assigned_to=user)


def _internal_assigned_by_queryset(user, user_profile):
    queryset = Task.objects.select_related('department', 'assigned_by', 'assigned_to')
    if user_profile.category == 'Task Management System Manager':
        return queryset.all()
    if user_profile.category == 'Departmental Manager' and user_profile.department_id:
        department = user_profile.department
        return queryset.filter(
            Q(assigned_by=user) |
            Q(assigned_by__userprofile__department=department) |
            Q(department=department)
        ).distinct()
    return queryset.filter(assigned_by=user)


def _external_assigned_to_queryset(user, user_profile):
    queryset = ClientTicket.objects.select_related('assigned_to', 'project_manager', 'department', 'ticket_type')
    if user_profile.category == 'Task Management System Manager':
        return queryset.all()
    if user_profile.category == 'Departmental Manager' and user_profile.department_id:
        department = user_profile.department
        return queryset.filter(
            Q(assigned_to=user) |
            Q(project_manager=user) |
            Q(department=department) |
            Q(assigned_to__userprofile__department=department) |
            Q(project_manager__userprofile__department=department)
        ).distinct()
    return queryset.filter(Q(assigned_to=user) | Q(project_manager=user)).distinct()


def _external_assigned_by_queryset(user, user_profile):
    queryset = ClientTicket.objects.select_related('assigned_to', 'project_manager', 'department', 'ticket_type')
    if user_profile.category == 'Task Management System Manager':
        return queryset.all()
    if user_profile.category == 'Departmental Manager' and user_profile.department_id:
        department = user_profile.department
        return queryset.filter(
            Q(created_by=user) |
            Q(project_manager=user) |
            Q(department=department) |
            Q(created_by__userprofile__department=department) |
            Q(project_manager__userprofile__department=department)
        ).distinct()
    return queryset.filter(Q(created_by=user) | Q(project_manager=user)).distinct()

@login_required
def home(request):
    user_profile = UserProfile.objects.get(user=request.user)
    today = date.today()
    print(today)
    if user_profile.category == 'Departmental Manager':
        # Fetch all tasks related to the department of the manager
        department = user_profile.department
        tasks = Task.objects.filter(
            # Tasks created by members of the manager's department
            Q(assigned_by__userprofile__department=department) |
            # Tasks assigned to members of the manager's department
            Q(assigned_to__userprofile__department=department)|
            Q(department__name=department),

            assigned_date__date__lte=today
        ).order_by('-assigned_date')
        
        return render(request, 'tasks/home.html', {
            'tasks': tasks,
            'departments': Department.objects.all(),
            'users':User.objects.all(),
        })

    return redirect('assigned_to_me')

@login_required
def assigned_to_me(request):
    user_profile = UserProfile.objects.select_related('department').get(user=request.user)
    mode = get_ticket_ui_mode(request)
    if mode == TICKET_MODE_EXTERNAL:
        queryset = _external_assigned_to_queryset(request.user, user_profile)
        queryset, selected_filters = _apply_external_filters(queryset, request)
        page_obj = _paginate_records(request, queryset.order_by('-updated_at', '-created_at'))
        return render(request, 'tasks/assigned_to_me.html', {
            'records': page_obj.object_list,
            'page_obj': page_obj,
            'page_title': 'Assigned to Me',
            'page_description': 'Track the external client tickets currently routed to you.',
            'summary': _external_summary(queryset),
            'selected_filters': selected_filters,
            'department_choices': Department.objects.all().order_by('name'),
            'user_type_choices': ClientTicket.USER_TYPE_CHOICES,
            'source_choices': ClientTicket.SOURCE_SYSTEM_CHOICES,
            'priority_choices': ClientTicket.PRIORITY_CHOICES,
            'status_choices': ClientTicket.STATUS_CHOICES[1:],
            'filter_query': _query_string_without_page(request),
        })

    queryset = _internal_assigned_to_queryset(request.user, user_profile)
    queryset, selected_filters = _apply_internal_filters(queryset, request)
    page_obj = _paginate_records(request, queryset.order_by('-assigned_date', '-deadline'))

    return render(request, 'tasks/assigned_to_me.html', {
        'records': page_obj.object_list,
        'page_obj': page_obj,
        'page_title': 'Assigned to Me',
        'page_description': 'Review and action the internal tickets currently assigned to you.',
        'summary': _internal_summary(queryset),
        'selected_filters': selected_filters,
        'department_choices': Department.objects.all().order_by('name'),
        'priority_choices': Task.PRIORITY_LEVELS,
        'status_choices': Task.STATUS_CHOICES,
        'filter_query': _query_string_without_page(request),
    })

@login_required
def assigned_by_me(request):
    user_profile = UserProfile.objects.select_related('department').get(user=request.user)
    mode = get_ticket_ui_mode(request)
    if mode == TICKET_MODE_EXTERNAL:
        queryset = _external_assigned_by_queryset(request.user, user_profile)
        queryset, selected_filters = _apply_external_filters(queryset, request)
        page_obj = _paginate_records(request, queryset.order_by('-updated_at', '-created_at'))
        return render(request, 'tasks/assigned_by_me.html', {
            'records': page_obj.object_list,
            'page_obj': page_obj,
            'page_title': 'Assigned By Me',
            'page_description': 'Monitor the external client tickets you have raised into the support flow.',
            'summary': _external_summary(queryset),
            'selected_filters': selected_filters,
            'department_choices': Department.objects.all().order_by('name'),
            'user_type_choices': ClientTicket.USER_TYPE_CHOICES,
            'source_choices': ClientTicket.SOURCE_SYSTEM_CHOICES,
            'priority_choices': ClientTicket.PRIORITY_CHOICES,
            'status_choices': ClientTicket.STATUS_CHOICES[1:],
            'filter_query': _query_string_without_page(request),
        })

    queryset = _internal_assigned_by_queryset(request.user, user_profile)
    queryset, selected_filters = _apply_internal_filters(queryset, request)
    page_obj = _paginate_records(request, queryset.order_by('-assigned_date', '-deadline'))

    return render(request, 'tasks/assigned_by_me.html', {
        'records': page_obj.object_list,
        'page_obj': page_obj,
        'page_title': 'Assigned By Me',
        'page_description': 'Keep track of the internal tickets you have created for the team.',
        'summary': _internal_summary(queryset),
        'selected_filters': selected_filters,
        'department_choices': Department.objects.all().order_by('name'),
        'priority_choices': Task.PRIORITY_LEVELS,
        'status_choices': Task.STATUS_CHOICES,
        'filter_query': _query_string_without_page(request),
    })


@login_required
@require_http_methods(['GET'])
def set_ticket_mode(request, mode):
    request.session['ticket_ui_mode'] = mode if mode in TICKET_MODE_CHOICES else TICKET_MODE_INTERNAL
    return redirect(_safe_ticket_redirect_target(request))

@login_required
def user_profile(request):
    # Display user profile details
    user_profile = UserProfile.objects.select_related('department').get(user=request.user)
    internal_assigned_to_queryset = _internal_assigned_to_queryset(request.user, user_profile)
    internal_assigned_by_queryset = _internal_assigned_by_queryset(request.user, user_profile)

    internal_ticket_summary = {
        'assigned_to_me': internal_assigned_to_queryset.count(),
        'assigned_by_me': internal_assigned_by_queryset.count(),
        'open_related': internal_assigned_to_queryset.exclude(status__in=['Completed', 'Cancelled']).count(),
        'urgent_related': internal_assigned_to_queryset.filter(priority='urgent').count(),
    }

    client_ticket_summary = {
        'assigned_to_me': 0,
        'project_managed': 0,
        'created_by_me': 0,
        'open_related': 0,
    }
    try:
        from client_tickets.models import ClientTicket

        related_tickets = ClientTicket.objects.filter(
            Q(assigned_to=request.user) |
            Q(project_manager=request.user) |
            Q(created_by=request.user)
        ).distinct()

        client_ticket_summary = {
            'assigned_to_me': ClientTicket.objects.filter(assigned_to=request.user).count(),
            'project_managed': ClientTicket.objects.filter(project_manager=request.user).count(),
            'created_by_me': ClientTicket.objects.filter(created_by=request.user).count(),
            'open_related': related_tickets.exclude(
                status__in=[
                    ClientTicket.STATUS_CLOSED,
                    ClientTicket.STATUS_AUTO_CLOSED,
                    ClientTicket.STATUS_CANCELLED,
                ]
            ).count(),
        }
    except ImportError:
        pass

    return render(
        request,
        'tasks/user_profile.html',
        {
            'user_profile': user_profile,
            'internal_ticket_summary': internal_ticket_summary,
            'client_ticket_summary': client_ticket_summary,
        }
    )

@login_required
def view_system_logs(request):
    # Placeholder for viewing system logs
    logs = ["Error 1: Task sync issue.", "Error 2: User permissions mismatch."]
    return render(request, 'tasks/system_logs.html', {'logs': logs})

def custom_403_view(request, exception=None):
    # Custom 403 Forbidden view to show a custom access denied message
    return render(request, '403.html', status=403)
@login_required
def task_list(request):
    """
    Display task list with filtering options for Task Management System Managers.
    For other users, display only tasks created by or assigned to them.
    """
    user_profile = UserProfile.objects.get(user=request.user)

    if user_profile.category == 'Task Management System Manager':
        tasks = Task.objects.all()  # Start with all tasks

        # Apply filters if provided
        department_id = request.GET.get('department')
        if department_id:
            tasks = tasks.filter(department_id=department_id)

        person_id = request.GET.get('person')
        if person_id:
            tasks = tasks.filter(Q(assigned_by_id=person_id) | Q(assigned_to_id=person_id))

        ageing_days = request.GET.get('ageing_days')
        if ageing_days:
            today = datetime.today().date()
            if ageing_days == 'overdue':
                tasks = tasks.filter(deadline__lt=today, status__in=['Not Started', 'In Progress', 'Stalled', 'On-Hold'])
            else:
                ageing_days = int(ageing_days)
                tasks = tasks.filter(assigned_date__lte=today - timedelta(days=ageing_days))

        status = request.GET.get('status')
        if status:
            if status == 'Overdue':
                today = date.today()
                tasks = tasks.filter(deadline__lt=today, status__in=['Not Started', 'In Progress', 'Stalled', 'On-Hold'])
            else:
                tasks = tasks.filter(status=status)

        departments = Department.objects.all()
        users = UserProfile.objects.filter(user__is_active=True)
        status_choices = TaskForm.STATUS_CHOICES

        return render(request, 'tasks/task_list.html', {
            'tasks': tasks,
            'departments': departments,
            'users': users,
            'status_choices': status_choices,
        })

    else:
        created_tasks = Task.objects.filter(assigned_by=request.user)
        assigned_tasks = Task.objects.filter(assigned_to=request.user)
        return render(request, 'tasks/task_list.html', {
            'created_tasks': created_tasks,
            'assigned_tasks': assigned_tasks,
        })


@login_required
def create_task(request):
    mode = get_ticket_ui_mode(request)

    if mode == TICKET_MODE_EXTERNAL:
        if request.method == 'POST':
            client_form = ClientTicketForm(request.POST, request.FILES, request=request)
            if client_form.is_valid():
                ticket = client_form.save(commit=False)
                client = upsert_client_contact(
                    client_form.cleaned_data['requester_name'],
                    client_form.cleaned_data['requester_email'],
                    client_form.cleaned_data['requester_number'],
                )
                ticket.requester = client
                ticket.created_by = request.user
                ticket.save()
                create_ticket_update(
                    ticket,
                    ClientTicketUpdate.ACTOR_INDITECH,
                    message='Ticket created from the main task screen.',
                    status=ticket.status,
                    user=request.user,
                    attachments=client_form.cleaned_data['attachments'],
                )
                notify_ticket_created(ticket)
                messages.success(request, f'Client ticket {ticket.ticket_number} created successfully.')
                return redirect('client_tickets:ticket_detail', ticket.ticket_number)
        else:
            client_form = ClientTicketForm(request=request)

        ticket_type_department_map = {
            ticket_type.id: ticket_type.department_id
            for ticket_type in ClientTicketType.objects.select_related('department').filter(is_active=True)
        }
        return render(request, 'tasks/create_task.html', {
            'client_form': client_form,
            'ticket_type_department_map': ticket_type_department_map,
        })

    if request.method == 'POST':
        form = TaskForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            task = form.save(commit=False)
            task.assigned_by = request.user  # Automatically set the assigned_by field
            task.assigned_date = date.today()
            task.save()
            form.save_m2m()

            # Notify the departmental manager (if exists)
            if task.department and hasattr(task.department, 'manager') and task.department.manager:
                manager_email = task.department.manager.email  # Ensure the manager's email exists
                view_ticket_url = request.build_absolute_uri(f'/tasks/detail/{task.task_id}/')
                context = {
                    'user': task.department.manager,
                    'ticket': task,
                    'view_ticket_url': view_ticket_url,
                }
                send_email_notification(
                    subject="New Task Created in Your Department",
                    template_name='emails/ticket_created.html',
                    context=context,
                    recipient_email=manager_email,
                )

            # Notify the assignee (if assigned)
            if task.assigned_to:
                assignee_email = task.assigned_to.email
                view_ticket_url = request.build_absolute_uri(f'/tasks/detail/{task.task_id}/')
                context = {
                    'user': task.assigned_to,
                    'ticket': task,
                    'view_ticket_url': view_ticket_url,
                }
                send_email_notification(
                    subject="You Have Been Assigned a New Task",
                    template_name='emails/ticket_assigned.html',
                    context=context,
                    recipient_email=assignee_email,
                    cc_emails=task.viewers,
                )

             # Notify the task creator
            creator_email = task.assigned_by.email
            view_ticket_url = request.build_absolute_uri(f'/tasks/detail/{task.task_id}/')
            context = {
                'user': task.assigned_by,
                'ticket': task,
                'view_ticket_url': view_ticket_url,
            }
            send_email_notification(
                subject="Your Task Has Been Created",
                template_name='emails/task_created_by_you.html',
                context=context,
                recipient_email=creator_email,
            )

            # Log the creation action
            ActivityLog.objects.create(
                action='created',
                user=request.user,
                task=task,
                description=f"Task {task.task_id} created by {request.user.username} for {task.assigned_to.username if task.assigned_to else 'Unassigned'}"
            )
            messages.success(request, f'Task {task.task_id} created successfully.')
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'message': 'Task created successfully!', 'task_id': task.task_id})
            return redirect('task_detail', task.task_id)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': 'Form data is invalid', 'errors': form.errors}, status=400)
        return render(request, 'tasks/create_task.html', {'form': form}, status=400)

    form = TaskForm(user=request.user)
    return render(request, 'tasks/create_task.html', {'form': form})

@login_required
def edit_task(request, task_id):
    task = get_object_or_404(Task, task_id=task_id)
    user_profile = UserProfile.objects.get(user=request.user)
    if task.assigned_by != request.user and not (
    user_profile.category == 'Departmental Manager' and
    task.assigned_by.userprofile.department == user_profile.department
    ):
        raise PermissionDenied

    old_priority = task.priority  # Capture the current priority before changes
    old_status = task.status

    if request.method == 'POST':
        form = TaskForm(request.POST, request.FILES, instance=task, user=request.user)
        if form.is_valid():
            updated_task = form.save()

            if old_status != updated_task.status:
                ActivityLog.objects.create(
                    action='status_changed',
                    user=request.user,
                    task=task,
                    description=f"Status changed from '{old_status}' to '{updated_task.status}'"
                )

            # Log priority change if it was updated
            if old_priority != updated_task.priority:
                ActivityLog.objects.create(
                    action='priority_changed',
                    user=request.user,
                    task=task,
                    description=f"Priority changed from {old_priority} to {updated_task.priority}"
                )

            return redirect('assigned_by_me')
        else:
            print("Form errors:", form.errors)  # Print form errors if the form is not valid
    else:
        form = TaskForm(instance=task, user=request.user)

    return render(request, 'tasks/edit_task.html', {'task': task, 'form': form})

@login_required
def task_detail(request, task_id):
    """
    Task detail view with chat functionality
    """
    # Fetch the task
    task = get_object_or_404(Task, task_id=task_id)
    
    # Check if user has permission to view this task
    user_profile = UserProfile.objects.get(user=request.user)
    is_viewer = request.user.email and request.user.email.lower() in (task.viewers or [])
    has_permission = (
        task.assigned_to == request.user or 
        task.assigned_by == request.user or 
        user_profile.category == 'Departmental Manager'
        or is_viewer
    )
    
    if not has_permission:
        messages.error(request, "You do not have permission to view this task.")
        return redirect('assigned_to_me')  # Redirect to a default view

    # Handle chat message submission
    if request.method == 'POST':
        chat_form = TaskChatForm(request.POST)
        if chat_form.is_valid():
            chat_message = chat_form.save(commit=False)
            chat_message.task = task
            chat_message.sender = request.user
            chat_message.save()
            send_new_message_notification(request, task, chat_message)
            messages.success(request, "Message sent successfully!")
            return redirect('task_detail', task_id=task_id)
    else:
        chat_form = TaskChatForm()

    # Fetch all chat messages for this task
    chat_messages = TaskChat.objects.filter(task=task).order_by('timestamp')

    context = {
        'task': task,
        'chat_form': chat_form,
        'chat_messages': chat_messages,
    }
    return render(request, 'tasks/task_detail.html', context)
def send_new_message_notification(request, task, chat_message):
    """
    Send email notification when a new message is added to a task
    """
    sender = chat_message.sender
    message_preview = chat_message.message[:100] + "..." if len(chat_message.message) > 100 else chat_message.message
    timestamp = chat_message.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    
    # Build the view message URL
    view_message_url = request.build_absolute_uri(f'/tasks/detail/{task.task_id}/')
    notification_settings_url = request.build_absolute_uri('/profile/notification-settings/')
    
    # Determine recipients (excluding the sender)
    recipients = []
    
    # If assigned_to exists and is not the sender, add to recipients
    if task.assigned_to and task.assigned_to != sender:
        recipients.append(task.assigned_to)
    
    # If assigned_by exists and is not the sender, add to recipients
    if task.assigned_by and task.assigned_by != sender:
        recipients.append(task.assigned_by)
    
    # Send emails to each recipient
    for recipient in recipients:
        context = {
            'user': recipient,
            'message': {
                'sender_name': f"{sender.first_name} {sender.last_name}",
                'subject': f"RE: {task.subject}",
                'timestamp': timestamp,
                'preview': message_preview
            },
            'view_message_url': view_message_url,
            'notification_settings_url': notification_settings_url,
        }
        
        send_email_notification(
            subject=f"New message on task #{task.task_id}: {task.subject}",
            template_name='emails/new_chat.html',
            context=context,
            recipient_email=recipient.email,
            cc_emails=task.viewers,
        )


@login_required
def update_task_status(request, task_id):
    task = get_object_or_404(Task, task_id=task_id)

    old_deadline = task.revised_completion_date
    old_comments = task.comments_by_assignee
    initial_deadline = task.deadline
    old_status = task.status  # Capture the old status

    if request.method == 'POST':
        form = TaskStatusUpdateForm(request.POST, instance=task)
        if form.is_valid():
            updated_task = form.save(commit=False)

            # Check if the status is being updated
            new_status = request.POST.get('status')
            if new_status:
                # Only the task owner (assigned_by) can mark status as "Completed"
                if new_status.lower() == 'completed' and request.user != task.assigned_by:
                    messages.error(request, "Only the task owner can mark the task as Completed.")
                    return render(request, 'tasks/update_task_status.html', {
                        'task': task, 
                        'form': form,
                        'error_message': 'Only the task owner can mark the task as Completed.'
                    })
                
                updated_task.status = new_status

            updated_task.save()  # Save the task with updated status

            # Notify about deadline revision if needed
            if old_deadline != updated_task.revised_completion_date:
                context = {
                    'ticket': updated_task,
                    'view_ticket_url': request.build_absolute_uri(f'/tasks/detail/{updated_task.task_id}/'),
                }
                send_email_notification(
                    subject=f"Deadline Revised: {updated_task.task_id}",
                    template_name='emails/ticket_deadline_updated.html',
                    context=context,
                    recipient_email=updated_task.assigned_by.email,
                    cc_emails=task.viewers,
                )
                if updated_task.assigned_to:
                    send_email_notification(
                        subject=f"Deadline Revised: {updated_task.task_id}",
                        template_name='emails/ticket_deadline_updated.html',
                        context=context,
                        recipient_email=updated_task.assigned_to.email,
                        cc_emails=task.viewers,
                    )

            # Notify about comment updates if needed
            if old_comments != updated_task.comments_by_assignee:
                context = {
                    'ticket': updated_task,
                    'view_ticket_url': request.build_absolute_uri(f'/tasks/detail/{updated_task.task_id}/'),
                }
                send_email_notification(
                    subject=f"Comment Updated: {updated_task.task_id}",
                    template_name='emails/ticket_comment_updated.html',
                    context=context,
                    recipient_email=updated_task.assigned_by.email,
                    cc_emails=task.viewers,
                )
                if updated_task.assigned_to:
                    send_email_notification(
                        subject=f"Comment Updated: {updated_task.task_id}",
                        template_name='emails/ticket_comment_updated.html',
                        context=context,
                        recipient_email=updated_task.assigned_to.email,
                        cc_emails=task.viewers,
                    )

            # Log the status update in ActivityLog
            if old_status != updated_task.status:
                ActivityLog.objects.create(
                    action='status_updated',
                    user=request.user,
                    task=updated_task,
                    description=f"Status changed from '{old_status}' to '{updated_task.status}'"
                )

            # Log deadline revision if needed
            if old_deadline != updated_task.revised_completion_date:
                ActivityLog.objects.create(
                    action='deadline_revised',
                    user=request.user,
                    task=updated_task,
                    description=f"Deadline revised from {initial_deadline} to {updated_task.revised_completion_date}"
                )

            # Log comment addition if needed
            if old_comments != updated_task.comments_by_assignee:
                ActivityLog.objects.create(
                    action='comment_added',
                    user=request.user,
                    task=updated_task,
                    description=f"Comment added or updated by assignee: {updated_task.comments_by_assignee}"
                )

            return redirect('task_detail', task_id=updated_task.task_id)
    else:
        form = TaskStatusUpdateForm(instance=task)

    return render(request, 'tasks/update_task_status.html', {'task': task, 'form': form})


@login_required
def send_deadline_reminders(request):
    send_deadline_reminders_logic()
    return HttpResponse("Deadline reminders sent!")

@login_required
def notify_overdue_tasks(request):
    notify_overdue_tasks_logic()
    return HttpResponse("Overdue notifications sent!")

@login_required
def mark_task_completed(request, task_id):
    task = get_object_or_404(Task, task_id=task_id)
    if task.assigned_by != request.user:
        raise PermissionDenied("Only the creator can mark this task as completed.")

    task.status_update_assignor = 'Completed'
    task.status_update_assignee = 'Completed'
    task.save()
    
    return redirect('task_detail', task_id=task.task_id)

@login_required
def reassign_task(request, task_id):
    task = get_object_or_404(Task, task_id=task_id)
    old_assignee = task.assigned_to  # Capture the current assignee before reassigning
    user_profile = UserProfile.objects.get(user=request.user)
    if task.assigned_to != request.user and not (
    user_profile.category == 'Departmental Manager' and
    task.assigned_to.userprofile.department == user_profile.department
    ):
        raise PermissionDenied

    

    # Redirect to a new page where user can add a note
    return redirect('task_note_page', task_id=task.task_id)  # Assuming 'task_note_page' is the new view for adding notes


@login_required
def task_note_page(request, task_id):
    task = get_object_or_404(Task, task_id=task_id)
    old_assignee = task.assigned_to
    user_profile = UserProfile.objects.get(user=request.user)
    if task.assigned_to != request.user and not (
    user_profile.category == 'Departmental Manager' and
    task.assigned_to.userprofile.department == user_profile.department
    ):
        raise PermissionDenied

    # Handle note addition and file attachment by assignee
    if request.method == 'POST':
        from django.utils import timezone
        
        note = request.POST.get('note')
        
        # Fetch existing notes and append new note with timestamp and user
        existing_notes = task.notes if task.notes else ""
        timestamp = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
        new_note_entry = f"{timestamp} - {note} - by {request.user.username}"
        
        # Append to existing notes (with separator if there are existing notes)
        if existing_notes:
            task.notes = f"{existing_notes}\n\n{new_note_entry}"
        else:
            task.notes = new_note_entry
        
        from_dept = task.assigned_by.userprofile.department

        # Handle the file attachment by assignee
        attachment = request.FILES.get('attachment_by_assignee')
        if attachment:
            task.attachment_by_assignee = attachment
            print("Attachment received:", attachment.name)

        task.assigned_to = task.assigned_by
        task.department = from_dept
        task.save()
        username = str(task.assigned_to)
        new_assignee = User.objects.get(username=username)
        view_ticket_url = request.build_absolute_uri(f'/tasks/detail/{task.task_id}/')
        context = {
                    'user': task.assigned_to,
                    'ticket': task,
                    'view_ticket_url': view_ticket_url,
                }

        if new_assignee.email:
            send_email_notification(
                    subject="You Have Been Re-Assigned a New Task",
                    template_name='emails/ticket_reassigned.html',
                    context=context,
                    recipient_email=new_assignee.email,
                    cc_emails=task.viewers,
                )

        # Log the reassignment
        ActivityLog.objects.create(
            action='reassigned',
            user=request.user,
            task=task,
            description=f"Task reassigned from {old_assignee.username} to {task.assigned_to.username}"
        )

        # Log the note addition
        ActivityLog.objects.create(
            action='comment_added',
            user=request.user,
            task=task,
            description=f"Note added by {request.user.username}: {note}"
        )

        return redirect('task_detail', task_id=task.task_id)

    return render(request, 'tasks/task_note_page.html', {'task': task})


@login_required
def dashboard(request):
    return redirect('assigned_to_me')

@login_required
def activity(request):
    # Fetch all activity logs for display, ordered by timestamp
    activity_logs = ActivityLog.objects.all().order_by('-timestamp')
    
    return render(request, 'tasks/activity.html', {
        'activity_logs': activity_logs
    })



@login_required
def download_activity_log(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="activity_log.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['User', 'Action', 'Task ID', 'Description', 'Timestamp'])
    
    logs = ActivityLog.objects.all().order_by('-timestamp')
    for log in logs:
        writer.writerow([log.user.username, log.get_action_display(), log.task.task_id, log.description, log.timestamp])
    
    return response

from django.db.models import F, Q, Count

@login_required
def metrics(request):
    # Get the current time and the last 24 hours time
    now = timezone.now()
    last_24_hours = now - timezone.timedelta(hours=24)
    seventy_two_hours_ago = now - timezone.timedelta(hours=72)
    today_date = now.date()

    # Get all departments for consistent metrics
    all_departments = Department.objects.all()
    
    # Initialize metrics_data list
    metrics_data = []
    
    for department in all_departments:
        department_name = department.name
        
        # RECEIVED TICKETS METRICS
        # Open tickets received by this department (status is not Completed or Cancelled)
        open_tickets_received = Task.objects.filter(
            department__name=department_name,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing', 'Stalled', 'On-Hold','Overdue']
        ).count()
        
        # Tickets received in last 24 hours by this department
        tickets_received_last_24hr = Task.objects.filter(
            department__name=department_name,
            assigned_date__gte=last_24_hours
        ).count()
        
        # RAISED TICKETS METRICS
        # Open tickets raised by this department (status is not Completed or Cancelled)
        open_tickets_raised = Task.objects.filter(
            assigned_by__userprofile__department__name=department_name,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing', 'Stalled', 'On-Hold','Overdue']
        ).count()
        
        # Tickets raised in last 24 hours by this department
        tickets_raised_last_24hr = Task.objects.filter(
            assigned_by__userprofile__department__name=department_name,
            assigned_date__gte=last_24_hours
        ).count()
        
        # OLDER TICKETS METRICS
        # Older open tickets (received more than 24 hours ago but still open)
        older_open_tickets = Task.objects.filter(
            department__name=department_name,
            assigned_date__lt=last_24_hours,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing', 'Stalled', 'On-Hold','Overdue']
        ).count()
        
        # PENDING TICKETS BIFURCATION
        # Get all tickets received by this department that are still open
        pending_tickets = Task.objects.filter(
            department__name=department_name,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing', 'Stalled', 'On-Hold','Overdue']
        )
        
        # Group these tickets by the department of the user who assigned them
        pending_by_dept = {}
        for task in pending_tickets:
            if task.assigned_by and hasattr(task.assigned_by, 'userprofile') and task.assigned_by.userprofile.department:
                assignor_dept_name = task.assigned_by.userprofile.department.name
                if assignor_dept_name not in pending_by_dept:
                    pending_by_dept[assignor_dept_name] = 0
                pending_by_dept[assignor_dept_name] += 1
        
        # TICKETS PASSED 72 HOURS
        # Tickets that were received more than 72 hours ago and are still open
        tickets_passed_72_hours = Task.objects.filter(
            department__name=department_name,
            assigned_date__lte=seventy_two_hours_ago,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing', 'Stalled', 'On-Hold','Overdue']
        ).count()
        
        # TICKETS PASSED DEADLINE
        # For each task, check if it has passed either the revised_completion_date or the original deadline
        tickets_passed_revised_deadline = Task.objects.filter(
            department__name=department_name,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing', 'Stalled', 'On-Hold','Overdue']
        ).filter(
            Q(revised_completion_date__isnull=False, revised_completion_date__lt=today_date) | 
            Q(revised_completion_date__isnull=True, deadline__lt=today_date)
        ).count()
        
        # Add all metrics for this department to the metrics_data list
        metrics_data.append({
            'department__name': department_name,
            'open_tickets_received': open_tickets_received,
            'tickets_received_last_24hr': tickets_received_last_24hr,
            'open_tickets_raised': open_tickets_raised,
            'tickets_raised_last_24hr': tickets_raised_last_24hr,
            'older_open_tickets': older_open_tickets,
            'pending_tickets_bifurcation': pending_by_dept,
            'tickets_passed_72_hours': tickets_passed_72_hours,
            'tickets_passed_revised_deadline': tickets_passed_revised_deadline
        })
    
    # Calculate summary totals
    total_open_raised = sum(d.get('open_tickets_raised', 0) for d in metrics_data)
    total_open_received = sum(d.get('open_tickets_received', 0) for d in metrics_data)
    total_raised_last_24hr = sum(d.get('tickets_raised_last_24hr', 0) for d in metrics_data)
    total_received_last_24hr = sum(d.get('tickets_received_last_24hr', 0) for d in metrics_data)
    total_older_open_tickets = sum(d.get('older_open_tickets', 0) for d in metrics_data)
    total_tickets_passed_72_hours = sum(d.get('tickets_passed_72_hours', 0) for d in metrics_data)
    total_tickets_passed_revised_deadline = sum(d.get('tickets_passed_revised_deadline', 0) for d in metrics_data)
    
    # Calculate total pending tickets
    total_pending_tickets = 0
    for department in metrics_data:
        pending_bifurcation = department.get('pending_tickets_bifurcation', {})
        total_pending_tickets += sum(pending_bifurcation.values())
    
    metrics_summary = {
        'total_raised_last_24hr': total_raised_last_24hr,
        'total_received_last_24hr': total_received_last_24hr,
        'total_open_raised': total_open_raised,
        'total_open_received': total_open_received,
        'total_older_open_tickets': total_older_open_tickets,
        'total_pending_tickets': total_pending_tickets,
        'total_tickets_passed_72_hours': total_tickets_passed_72_hours,
        'total_tickets_passed_revised_deadline': total_tickets_passed_revised_deadline,
    }
    
    return render(request, 'tasks/metrics.html', {
        'metrics_data': metrics_data,
        'metrics_summary': metrics_summary,
    })

# Download metrics as a CSV file

@login_required
def download_metrics(request):
    # Get the current time and the last 24 hours time
    now = timezone.now()
    last_24_hours = now - timezone.timedelta(hours=24)
    today_date = date.today()
    seventy_two_hours = now - timedelta(hours=72)

    # Metrics for Last 24 Hours (raised and received)
    metrics_data = Task.objects.values('department__name').annotate(
        tickets_received_last_24hr=Count('id', filter=Q(assigned_to__userprofile__department__name=F('department__name'), assigned_date__gte=last_24_hours, assigned_date__lte=today_date)),
        open_tickets_received=Count('id', filter=Q(assigned_to__userprofile__department__name=F('department__name'), status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing'], assigned_date__lte=today_date)),
    ).order_by('department__name')

    # Add all-time data for raised and received tickets
    for data in metrics_data:
        department_name = data['department__name']

        tickets_raised_all_time = Task.objects.filter(
            assigned_by__userprofile__department__name=department_name,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing','Overdue'],
            assigned_date__lte=today_date
        ).count()

        tickets_raised_last_24hr = Task.objects.filter(
            assigned_by__userprofile__department__name=department_name,
            assigned_date__gte=last_24_hours,
            assigned_date__lte=today_date
        ).count()

        data['tickets_raised_last_24hr'] = tickets_raised_last_24hr

        tickets_received_all_time = Task.objects.filter(
            assigned_to__userprofile__department__name=department_name,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing','Overdue'],
            assigned_date__lte=today_date
        ).count()

        data['open_tickets_raised'] = tickets_raised_all_time
        data['open_tickets_received'] = tickets_received_all_time

        # Tickets passed 72 hours after raising
        passed_72_hours = Task.objects.filter(
            department__name=department_name,
            assigned_date__lte=seventy_two_hours,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing','Overdue'],
        ).count()
        data['tickets_passed_72_hours'] = passed_72_hours
        
        # Tickets passed the revised deadline or original deadline
        passed_revised_deadline = Task.objects.filter(
            department__name=department_name,
            deadline__lte=now,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing','Overdue'],
        ).count()
        data['tickets_passed_revised_deadline'] = passed_revised_deadline

        # Get older open tickets with task data
        older_open_tickets_data = Task.objects.filter(
            assigned_to__userprofile__department__name=department_name,
            status__in=['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing','Overdue'],
            assigned_date__lt=last_24_hours
        )
        data['older_open_tickets'] = older_open_tickets_data  # Storing actual task data

    # Add Pending Tickets by Department (Bifurcation)
    for data in metrics_data:
        department_name = data['department__name']

        # Filter tasks where assigned_to department matches the current department
        all_task_of_this_dept = Task.objects.filter(
            assigned_to__userprofile__department__name=department_name,
            status__in=['In Progress', 'Not Started', 'Pending', 'Processing', 'Delay Processing', 'Waiting for confirmation','Overdue'],
            assigned_date__lt=last_24_hours
        )

        # Create a map to store pending tickets count by assigned_by department
        pending_by_dept = {}

        # Loop through tasks and populate pending_by_dept map
        for task in all_task_of_this_dept:
            assignor_dept_name = task.assigned_by.userprofile.department.name  # Updated variable name

            # Increment the pending ticket count for the assignor department
            if assignor_dept_name not in pending_by_dept:
                pending_by_dept[assignor_dept_name] = 0
            pending_by_dept[assignor_dept_name] += 1

        # Set the pending_by_dept map as the bifurcation value
        data['pending_tickets_bifurcation'] = pending_by_dept

    # Prepare CSV Response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="metrics_data.csv"'

    writer = csv.writer(response)

    # Writing the header row
    writer.writerow([
        'Department Name',
        'Tickets Received Last 24hr',
        'Open Tickets Received',
        'Tickets Raised Last 24hr',
        'Open Tickets Raised',
        'Older Open Tickets',
        'Pending Tickets Bifurcation',
        'Tickets Passed 72 Hours After Raising',  # New Column Header
        'Tickets Passed the Revised Deadline'   # New Column Header
    ])

    # Writing data rows
    for data in metrics_data:
        department_name = data['department__name']
        tickets_received_last_24hr = data['tickets_received_last_24hr']
        open_tickets_received = data['open_tickets_received']
        tickets_raised_last_24hr = data['tickets_raised_last_24hr']
        open_tickets_raised = data['open_tickets_raised']
        older_open_tickets = len(data['older_open_tickets'])  # Assuming this is a list of task objects
        pending_tickets_bifurcation = str(data['pending_tickets_bifurcation'])  # Convert to string for CSV format
        tickets_passed_72_hours = data['tickets_passed_72_hours']
        tickets_passed_revised_deadline = data['tickets_passed_revised_deadline']

        writer.writerow([
            department_name,
            tickets_received_last_24hr,
            open_tickets_received,
            tickets_raised_last_24hr,
            open_tickets_raised,
            older_open_tickets,
            pending_tickets_bifurcation,
            tickets_passed_72_hours,  # New Column Data
            tickets_passed_revised_deadline  # New Column Data
        ])

    return response

@login_required
def reassign_within_department(request, task_id):
    task = get_object_or_404(Task, task_id=task_id)
    user_profile = UserProfile.objects.get(user=request.user)

    # Ensure only Departmental Managers can access this functionality
    if user_profile.category != 'Departmental Manager':
        raise PermissionDenied("Only Departmental Managers can reassign tasks.")

    # Fetch non-management users in the same department
    non_management_users = UserProfile.objects.filter(
        department=user_profile.department,
        category='Non-Management'
    )

    if request.method == 'POST':
        new_assignee_id = request.POST.get('assigned_to')
        if new_assignee_id:
            new_assignee = get_object_or_404(User, id=new_assignee_id)
            task.assigned_to = new_assignee
            task.save()

            # Notify the assignee (if assigned)
            if task.assigned_to:
                assignee_email = task.assigned_to.email
                view_ticket_url = request.build_absolute_uri(f'/tasks/detail/{task.task_id}/')
                context = {
                    'user': task.assigned_to,
                    'ticket': task,
                    'view_ticket_url': view_ticket_url,
                }
                send_email_notification(
                    subject="You Have Been Assigned a New Task",
                    template_name='emails/ticket_assigned.html',
                    context=context,
                    recipient_email=assignee_email,
                    cc_emails=task.viewers,
                )


            # Log the reassignment action
            ActivityLog.objects.create(
                action='assigned',
                user=request.user,
                task=task,
                description=f"Task {task.task_id} reassigned from {request.user.username} to {new_assignee.username}"
            )
            return redirect('task_detail', task_id=task.task_id)

    return render(request, 'tasks/reassign_within_department.html', {
        'task': task,
        'non_management_users': non_management_users,
    })

# task_app/views.py

@login_required
def department_metrics(request, department):
    # Fetch the department object
    department_obj = get_object_or_404(Department, name=department)

    # Get the current time and the last 24 hours time
    now = timezone.now()
    last_24_hours = now - timezone.timedelta(hours=24)
    today_date = now.date()
    seventy_two_hours = now - timezone.timedelta(hours=72)

    # Define the status options to filter open tickets
    open_statuses = ['In Progress', 'Not Started', 'Waiting for confirmation', 'Pending', 'Delay processing', 'Processing', 'Stalled', 'On-Hold','Overdue']

    # Metrics calculations for the department
    open_tickets_received = Task.objects.filter(
        department=department_obj,
        status__in=open_statuses
    ).count()

    tickets_received_last_24hr = Task.objects.filter(
        department=department_obj,
        assigned_date__gte=last_24_hours
    ).count()

    open_tickets_raised = Task.objects.filter(
        assigned_by__userprofile__department=department_obj,
        status__in=open_statuses
    ).count()

    tickets_raised_last_24hr = Task.objects.filter(
        assigned_by__userprofile__department=department_obj,
        assigned_date__gte=last_24_hours
    ).count()

    older_open_tickets = Task.objects.filter(
        department=department_obj,
        assigned_date__lt=last_24_hours,
        status__in=open_statuses
    ).count()

    # Group pending tickets by the department of the user who assigned them
    # This shows tickets that OTHER departments have assigned TO current department
    pending_tickets = Task.objects.filter(
        department=department_obj,
        status__in=open_statuses
    )

    pending_by_dept = {}
    for task in pending_tickets:
        assignor_dept_name = task.assigned_by.userprofile.department.name
        if assignor_dept_name not in pending_by_dept:
            pending_by_dept[assignor_dept_name] = 0
        pending_by_dept[assignor_dept_name] += 1

    # NEW FIELD: Group tickets assigned BY current department to other departments
    # This shows tickets that current department has assigned to OTHER departments
    tickets_assigned_by_current_dept = Task.objects.filter(
        assigned_by__userprofile__department=department_obj,  # assigned_by's department = current department
        status__in=open_statuses
    )

    tickets_assigned_to_other_depts = {}
    for task in tickets_assigned_by_current_dept:
        receiver_dept_name = task.department # which department received the task
        if receiver_dept_name not in tickets_assigned_to_other_depts:
            tickets_assigned_to_other_depts[receiver_dept_name] = 0
        tickets_assigned_to_other_depts[receiver_dept_name] += 1

    tickets_passed_72_hours = Task.objects.filter(
        department=department_obj,
        assigned_date__lte=seventy_two_hours,
        status__in=open_statuses
    ).count()

    tickets_passed_revised_deadline = Task.objects.filter(
        department=department_obj,
        status__in=open_statuses
    ).filter(
        Q(revised_completion_date__isnull=False, revised_completion_date__lt=today_date) |
        Q(revised_completion_date__isnull=True, deadline__lt=today_date)
    ).count()

    # Aggregate metrics into a dictionary
    department_metrics_data = {
        'open_tickets_received': open_tickets_received,
        'tickets_received_last_24hr': tickets_received_last_24hr,
        'open_tickets_raised': open_tickets_raised,
        'tickets_raised_last_24hr': tickets_raised_last_24hr,
        'older_open_tickets': older_open_tickets,
        'pending_tickets_bifurcation': pending_by_dept,
        'tickets_assigned_to_other_depts': tickets_assigned_to_other_depts,  # NEW FIELD
        'tickets_passed_72_hours': tickets_passed_72_hours,
        'tickets_passed_revised_deadline': tickets_passed_revised_deadline
    }


    # Render the department-wise metrics page
    return render(request, 'tasks/department_metrics.html', {
        'department_metrics_data': department_metrics_data,
        'department_name': department_obj.name
    })
from django.http import Http404
# View to list, edit, and delete users
@login_required
def manage_users(request):
    user_profile = UserProfile.objects.get(user=request.user)

    # Ensure that only a departmental manager can access this page
    if user_profile.category != 'Departmental Manager':
        raise Http404("You do not have permission to view this page.")

    # Fetch users in the same department as the manager
    department = user_profile.department
    users = User.objects.filter(userprofile__department=department)

    # Handle adding a new user
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            username = request.POST.get("username")
            first_name = request.POST.get("first_name")
            last_name = request.POST.get("last_name")
            email = request.POST.get("email")
            password = request.POST.get("password")
            try:
                # Create user with first name and last name
                user = User.objects.create_user(username=username, email=email, password=password,
                                                first_name=first_name, last_name=last_name)
                UserProfile.objects.create(user=user, category='Non-Management', department=department)
                messages.success(request, f"User {username} added successfully!")
            except Exception as e:
                messages.error(request, f"Error adding user: {e}")
        elif action == "delete":
            user_id = request.POST.get("user_id")
            user = get_object_or_404(User, id=user_id)
            if user.userprofile.department == department:
                user.delete()
                messages.success(request, "User deleted successfully!")
            else:
                messages.error(request, "You can only delete users from your department.")
        elif action == "edit":
            user_id = request.POST.get("user_id")
            new_username = request.POST.get("username")
            new_email = request.POST.get("email")
            first_name = request.POST.get("first_name")
            last_name = request.POST.get("last_name")
            user = get_object_or_404(User, id=user_id)
            if user.userprofile.department == department:
                user.username = new_username
                user.email = new_email
                user.first_name = first_name
                user.last_name = last_name
                user.save()
                messages.success(request, "User updated successfully!")
            else:
                messages.error(request, "You can only edit users from your department.")
    
    return render(request, 'tasks/manage_users.html', {'users': users})
def general_manage_users(request):
    """
    General user management page without authentication
    Allows adding, editing, and deleting users with category selection
    """
    
    # Get all users and departments for the page
    users = User.objects.all().select_related('userprofile')
    departments = Department.objects.all()
    
    # Category choices for UserProfile
    CATEGORY_CHOICES = [
        ('Task Management System Manager', 'Task Management System Manager'),
        ('Non-Management', 'Non-Management'),
        ('Executive Management', 'Executive Management'),
        ('Departmental Manager', 'Departmental Manager'),
    ]

    if request.method == "POST":
        action = request.POST.get("action")
        
        if action == "add":
            username = request.POST.get("username")
            first_name = request.POST.get("first_name")
            last_name = request.POST.get("last_name")
            email = request.POST.get("email")
            password = request.POST.get("password")
            category = request.POST.get("category")
            department_id = request.POST.get("department")
            
            try:
                # Check if username already exists
                if User.objects.filter(username=username).exists():
                    messages.error(request, f"Username '{username}' already exists!")
                    return redirect('general_manage_users')
                
                # Check if email already exists
                if User.objects.filter(email=email).exists():
                    messages.error(request, f"Email '{email}' already exists!")
                    return redirect('general_manage_users')
                
                # Get department object
                department = get_object_or_404(Department, id=department_id) if department_id else None
                
                # Create user
                user = User.objects.create_user(
                    username=username, 
                    email=email, 
                    password=password,
                    first_name=first_name, 
                    last_name=last_name
                )
                
                # Create or update user profile
                UserProfile.objects.create(
                    user=user, 
                    category=category, 
                    department=department
                )
                
                messages.success(request, f"User '{username}' added successfully!")
                
            except Exception as e:
                messages.error(request, f"Error adding user: {str(e)}")
                
        elif action == "edit":
            user_id = request.POST.get("user_id")
            new_username = request.POST.get("username")
            new_email = request.POST.get("email")
            first_name = request.POST.get("first_name")
            last_name = request.POST.get("last_name")
            category = request.POST.get("category")
            department_id = request.POST.get("department")
            
            try:
                user = get_object_or_404(User, id=user_id)
                
                # Check if username already exists for other users
                if User.objects.filter(username=new_username).exclude(id=user_id).exists():
                    messages.error(request, f"Username '{new_username}' already exists!")
                    return redirect('general_manage_users')
                
                # Check if email already exists for other users
                if User.objects.filter(email=new_email).exclude(id=user_id).exists():
                    messages.error(request, f"Email '{new_email}' already exists!")
                    return redirect('general_manage_users')
                
                # Get department object
                department = get_object_or_404(Department, id=department_id) if department_id else None
                
                # Update user
                user.username = new_username
                user.email = new_email
                user.first_name = first_name
                user.last_name = last_name
                user.save()
                
                # Update user profile
                user_profile, created = UserProfile.objects.get_or_create(user=user)
                user_profile.category = category
                user_profile.department = department
                user_profile.save()
                
                messages.success(request, f"User '{new_username}' updated successfully!")
                
            except Exception as e:
                messages.error(request, f"Error updating user: {str(e)}")
                
        elif action == "delete":
            user_id = request.POST.get("user_id")
            try:
                user = get_object_or_404(User, id=user_id)
                username = user.username
                user.delete()
                messages.success(request, f"User '{username}' deleted successfully!")
            except Exception as e:
                messages.error(request, f"Error deleting user: {str(e)}")
    
    context = {
        'users': users,
        'departments': departments,
        'categories': CATEGORY_CHOICES,
    }
    
    return render(request, 'tasks/general_manage_users.html', context)
from urllib.parse import unquote
def get_user_by_email(email):
    """Helper function to get user by email"""
    try:
        return User.objects.filter(email=email).first()
    except User.DoesNotExist:
        return None

@require_http_methods(["GET"])
def api_create_task(request, assigned_by_email, assigned_to_email, deadline, ticket_type, priority, department, subject, request_details):
    """
    Create task via GET request with URL parameters
    URL Format: /api/create-task/{assigned_by_email}/{assigned_to_email}/{deadline}/{ticket_type}/{priority}/{department}/{subject}/{request_details}/
    
    Example: /api/create-task/sanyam.jain@inditech.co.in/khushan.poptani@inditech.co.in/2024-12-31/Issues/High/IT/Server-Down/Server-not-responding/
    
    Optional parameters via query string:
    - status (default: Open)
    - is_recurring (default: false)
    - recurrence_type 
    - recurrence_count
    - recurrence_duration
    """
    import re
    try:
        # Decode URL parameters (in case of special characters)
        assigned_by_email = unquote(assigned_by_email)
        assigned_to_email = unquote(assigned_to_email) if assigned_to_email.lower() != 'none' else None
        deadline = unquote(deadline) if deadline.lower() != 'none' else None
        ticket_type = unquote(ticket_type)
        priority = unquote(priority)
        department = unquote(department) if department.lower() != 'none' else None
        subject = unquote(subject).replace('-', ' ')  # Convert hyphens back to spaces
        request_details = unquote(request_details).replace('-', ' ')
        # Optional viewers via querystring: ?viewer_emails=a@x.com,b@y.com
        raw_viewers = request.GET.get("viewer_emails") or ""
        viewers = []
        if raw_viewers:
            for e in raw_viewers.split(","):
                e = e.strip().lower()
                if e:
                    viewers.append(e)

        # Get users by email
        assigned_by_user = get_user_by_email(assigned_by_email)
        if not assigned_by_user:
            return JsonResponse({
                'error': f'User with email {assigned_by_email} not found',
                'success': False
            }, status=404)

        assigned_to_user = None
        if assigned_to_email:
            assigned_to_user = get_user_by_email(assigned_to_email)
            if not assigned_to_user:
                return JsonResponse({
                    'error': f'Assignee with email {assigned_to_email} not found',
                    'success': False
                }, status=404)

        # Parse deadline
        parsed_deadline = None
        if deadline:
            from django.utils.dateparse import parse_date
            parsed_deadline = parse_date(deadline)
            if not parsed_deadline:
                return JsonResponse({
                    'error': 'Invalid deadline format. Use YYYY-MM-DD',
                    'success': False
                }, status=400)

        # Get optional parameters from query string
        status = request.GET.get('status', 'Not Started')
        is_recurring = request.GET.get('is_recurring', 'false').lower() == 'true'
        recurrence_type = request.GET.get('recurrence_type', '') if is_recurring else ''
        recurrence_count = int(request.GET.get('recurrence_count', 0)) if is_recurring else 0
        recurrence_duration = int(request.GET.get('recurrence_duration', 0)) if is_recurring else 0

        # Create task
        from datetime import date
        task = Task(
            assigned_by=assigned_by_user,
            assigned_to=assigned_to_user,
            assigned_date=date.today(),
            deadline=parsed_deadline,
            ticket_type=ticket_type,
            priority=priority,
            department_id=department if department else None,
            subject=subject,
            request_details=request_details,
            status=status,
            is_recurring=is_recurring,
            recurrence_type=recurrence_type,
            recurrence_count=recurrence_count,
            recurrence_duration=recurrence_duration,
            viewers=sorted(list(set(viewers))),
        )

        # Validate and save
        try:
            from django.core.exceptions import ValidationError
            task.full_clean()
            task.save()
        except ValidationError as e:
            return JsonResponse({
                'error': 'Validation failed',
                'validation_errors': e.message_dict,
                'success': False
            }, status=400)

        # Send email notifications (reusing your existing logic)
        try:
            if task.assigned_to:
                view_ticket_url = f'/tasks/detail/{task.task_id}/'
                context = {
                    'user': task.assigned_to,
                    'ticket': task,
                    'view_ticket_url': view_ticket_url,
                }
                send_email_notification(
                    subject="You Have Been Assigned a New Task",
                    template_name='emails/ticket_assigned.html',
                    context=context,
                    recipient_email=task.assigned_to.email,
                    cc_emails=task.viewers,
                )

            # Notify task creator
            view_ticket_url = f'/tasks/detail/{task.task_id}/'
            context = {
                'user': task.assigned_by,
                'ticket': task,
                'view_ticket_url': view_ticket_url,
            }
            send_email_notification(
                subject="Your Task Has Been Created",
                template_name='emails/task_created_by_you.html',
                context=context,
                recipient_email=task.assigned_by.email,
                cc_emails=task.viewers,
            )

        except Exception as e:
            logger.warning(f"Failed to send email notifications for task {task.task_id}: {str(e)}")

        # Log the creation action
        try:
            ActivityLog.objects.create(
                action='created',
                user=assigned_by_user,
                task=task,
                description=f"Task {task.task_id} created by {assigned_by_user.username} via GET API"
            )
        except Exception as e:
            logger.warning(f"Failed to log activity for task {task.task_id}: {str(e)}")

        return JsonResponse({
            'message': 'Task created successfully via GET!',
            'task_id': task.task_id,
            'success': True,
            'redirect_url': f'/tasks/detail/{task.task_id}/'  # Optional redirect
        }, status=201)

    except Exception as e:
        logger.error(f"Unexpected error in api_create_task: {str(e)}")
        return JsonResponse({
            'error': 'Internal server error',
            'success': False
        }, status=500)
from urllib.parse import unquote_plus

def _parse_viewers(raw: str | None):
    if not raw:
        return []
    parts = [p.strip().lower() for p in unquote_plus(raw).split(",")]
    return sorted(list({p for p in parts if p}))
@require_http_methods(["GET"])
def api_update_viewers(request, task_id, viewer_emails):
    """
    Replace the viewer list of a task.
    URL: /api/update-viewers/<task_id>/<path:viewer_emails>/
    Use 'none' to clear the list.
    """
    task = get_object_or_404(Task, task_id=task_id)

    # Authorization: creator, current assignee, or departmental manager only
    user_profile = UserProfile.objects.get(user=request.user)
    is_manager = user_profile.category == 'Departmental Manager'
    if not (task.assigned_by == request.user or task.assigned_to == request.user or is_manager):
        return JsonResponse({"error": "Forbidden"}, status=403)

    if viewer_emails.lower() == "none":
        new_viewers = []
    else:
        emails = [e.strip().lower() for e in viewer_emails.split(",") if e.strip()]
        new_viewers = sorted(list(set(emails)))

    task.viewers = new_viewers
    task.save(update_fields=["viewers"])

    return JsonResponse({"task_id": task.task_id, "viewers": task.viewers})

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from urllib.parse import unquote
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

@require_http_methods(["GET"])
def api_update_task(request, task_id, updated_by_email, status=None, revised_deadline=None, subject=None, request_details=None):
    """
    Update task via GET request with optional subject and request details
    URL Format 1: /api/update-task/{task_id}/{updated_by_email}/{status}/{revised_deadline}/
    URL Format 2: /api/update-task/{task_id}/{updated_by_email}/{status}/{revised_deadline}/{subject}/{request_details}/
    
    Example 1: /api/update-task/TEC-K0QCMM/user@inditech.co.in/In%20Progress/2025-09-04/
    Example 2: /api/update-task/TEC-K0QCMM/user@inditech.co.in/In%20Progress/2025-09-04/Fix-login/Password-issue/
    
    Optional parameters via query string:
    - comments_by_assignee
    """
    try:
        # Decode parameters
        updated_by_email = unquote(updated_by_email)
        status = unquote(status) if status and status.lower() != 'none' else None
        revised_deadline = unquote(revised_deadline) if revised_deadline and revised_deadline.lower() != 'none' else None
        subject = unquote(subject) if subject and subject.lower() != 'none' else None
        request_details = unquote(request_details) if request_details and request_details.lower() != 'none' else None
        
        # Get task
        try:
            task = Task.objects.get(task_id=task_id)
        except Task.DoesNotExist:
            return JsonResponse({
                'error': f'Task with ID {task_id} not found',
                'success': False
            }, status=404)

        # Get user
        updated_by_user = get_user_by_email(updated_by_email)
        if not updated_by_user:
            return JsonResponse({
                'error': f'User with email {updated_by_email} not found',
                'success': False
            }, status=404)

        # Authorization check
        is_creator = task.assigned_by == updated_by_user
        is_assignee = task.assigned_to == updated_by_user
        
        if not (is_creator or is_assignee):
            return JsonResponse({
                'error': 'Unauthorized: You can only update tasks you created or are assigned to',
                'success': False
            }, status=403)

        # Store original values
        old_status = task.status
        old_deadline = task.revised_completion_date
        changes_made = []

        # Update status
        if status and status.replace('-', ' ') != old_status:
            task.status = status.replace('-', ' ')
            changes_made.append(f"status: {old_status} -> {task.status}")
        if subject and subject.replace('-', ' ') != task.subject:
            task.subject = subject.replace('-', ' ')
            changes_made.append("subject updated")
        if request_details and request_details.replace('-', ' ') != task.request_details:
            task.request_details = request_details.replace('-', ' ')    
            changes_made.append("request_details updated")

        # Update revised deadline
        if revised_deadline:
            from django.utils.dateparse import parse_date
            parsed_date = parse_date(revised_deadline)
            if not parsed_date:
                return JsonResponse({
                    'error': 'Invalid revised_deadline format. Use YYYY-MM-DD',
                    'success': False
                }, status=400)
            
            if old_deadline != parsed_date:
                task.revised_completion_date = parsed_date
                changes_made.append(f"revised_deadline: {old_deadline} -> {parsed_date}")

        # Update comments from query parameter
        comments = request.GET.get('comments_by_assignee')
        if comments and comments != task.comments_by_assignee:
            task.comments_by_assignee = comments
            changes_made.append("comments updated")
        # Handle subject and request_details updates
        if subject or request_details:
            # Create update message in the specified format
            update_message = ""
            current_date = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if subject:
                update_message += f"Update Subject: {subject}\n"
            
            update_message += f"Update date: {current_date}\n"
            
            if request_details:
                update_message += f"Update details: {request_details}\n"
            
            changes_made.append("subject/details updated via API")

        if not changes_made:
            return JsonResponse({
                'message': 'No changes detected',
                'task_id': task.task_id,
                'success': True
            })

        # Save task
        task.save()

        # Send notifications based on who updated the task
        try:
            view_ticket_url = f'/tasks/detail/{task.task_id}/'
            context = {'ticket': task, 'view_ticket_url': view_ticket_url}
            
            # Determine email recipient based on who made the update
            recipient_email = None
            email_subject = f"Task Updated: {task.task_id}"
            
            if is_creator:
                # If creator updated, send email to assignee
                if task.assigned_to and task.assigned_to.email:
                    recipient_email = task.assigned_to.email
                    email_subject = f"Task Updated by Creator: {task.task_id}"
            elif is_assignee:
                # If assignee updated, send email to creator
                if task.assigned_by and task.assigned_by.email:
                    recipient_email = task.assigned_by.email
                    email_subject = f"Task Updated by Assignee: {task.task_id}"
            
            if recipient_email:
                send_email_notification(
                    subject=email_subject,
                    template_name='emails/ticket_status_updated.html',
                    context=context,
                    recipient_email=recipient_email,
                    cc_emails=task.viewers,
                )

        except Exception as e:
            logger.warning(f"Failed to send email notifications: {str(e)}")

        # Log activity
        try:
            activity_description = f"Task updated via GET API by {updated_by_user.email}"
            if old_status != task.status:
                activity_description += f" - Status changed from '{old_status}' to '{task.status}'"
            if subject:
                activity_description += f" - Subject updated to '{subject}'"
            if request_details:
                activity_description += f" - Request details updated"
                
            ActivityLog.objects.create(
                action='task_updated_api',
                user=updated_by_user,
                task=task,
                description=activity_description
            )
        except Exception as e:
            logger.warning(f"Failed to log activity: {str(e)}")

        return JsonResponse({
            'message': 'Task updated successfully via GET API!',
            'task_id': task.task_id,
            'changes_made': changes_made,
            'updated_by': updated_by_user.email,
            'success': True
        })

    except Exception as e:
        logger.error(f"Unexpected error in api_update_task: {str(e)}")
        return JsonResponse({
            'error': 'Internal server error',
            'success': False
        }, status=500)

@require_http_methods(["GET"])
def api_reassign_task(request, task_id, reassigned_by_email):
    """
    Reassign task via GET request
    URL Format: /api/reassign-task/{task_id}/{reassigned_by_email}/
    
    Example: /api/reassign-task/12345/sanyam.jain@inditech.co.in/
    
    Optional parameters via query string:
    - note
    """
    try:
        # Decode parameters
        reassigned_by_email = unquote(reassigned_by_email)
        
        # Get task
        try:
            task = Task.objects.get(task_id=task_id)
        except Task.DoesNotExist:
            return JsonResponse({
                'error': f'Task with ID {task_id} not found',
                'success': False
            }, status=404)

        # Get user
        reassigned_by_user = get_user_by_email(reassigned_by_email)
        if not reassigned_by_user:
            return JsonResponse({
                'error': f'User with email {reassigned_by_email} not found',
                'success': False
            }, status=404)

        # Store original assignee
        old_assignee = task.assigned_to
        old_assignee_name = old_assignee.username if old_assignee else 'Unassigned'

        # Handle note from query parameter
        note = request.GET.get('note', '')
        if note:
            task.notes = note

        # Reassign back to creator (following your existing logic)
        from_dept = task.assigned_by.userprofile.department
        task.assigned_to = task.assigned_by
        task.department = from_dept
        task.save()

        new_assignee = task.assigned_by

        # Send notifications (reusing your existing logic)
        try:
            view_ticket_url = f'/tasks/detail/{task.task_id}/'
            context = {
                'user': new_assignee,
                'ticket': task,
                'view_ticket_url': view_ticket_url,
            }

            if new_assignee.email:
                send_email_notification(
                    subject="You Have Been Re-Assigned a Task",
                    template_name='emails/ticket_reassigned.html',
                    context=context,
                    recipient_email=new_assignee.email,
                    cc_emails=task.viewers,
                )

        except Exception as e:
            logger.warning(f"Failed to send email notifications: {str(e)}")

        # Log activity
        try:
            ActivityLog.objects.create(
                action='reassigned',
                user=reassigned_by_user,
                task=task,
                description=f"Task reassigned via GET API from {old_assignee_name} to {new_assignee.username}"
            )

            if note:
                ActivityLog.objects.create(
                    action='comment_added',
                    user=reassigned_by_user,
                    task=task,
                    description=f"Note added via GET API: {note}"
                )

        except Exception as e:
            logger.warning(f"Failed to log activity: {str(e)}")

        return JsonResponse({
            'message': 'Task reassigned successfully via GET!',
            'task_id': task.task_id,
            'previous_assignee': old_assignee_name,
            'new_assignee': new_assignee.username,
            'success': True
        })

    except Exception as e:
        logger.error(f"Unexpected error in api_reassign_task: {str(e)}")
        return JsonResponse({
            'error': 'Internal server error',
            'success': False
        }, status=500)
    

@login_required
def i_am_viewer(request):
    me = (request.user.email or "").lower()
    tasks = Task.objects.filter(viewers__contains=[me]).order_by("-assigned_date")
    return render(request, "tasks/i_am_viewer.html", {"tasks": tasks})
