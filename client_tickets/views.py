import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from task_app.models import Department

from .forms import ClientTicketClientUpdateForm, ClientTicketForm, ClientTicketInditechUpdateForm
from .models import ClientContact, ClientTicket, ClientTicketType, ClientTicketUpdate
from .services import (
    create_ticket_update,
    notify_ticket_created,
    notify_ticket_updated,
    send_daily_summary_emails,
    send_unchecked_ticket_reminders,
    ticket_to_dict,
    upsert_client_contact,
    auto_close_stale_tickets,
)
from .utils import normalize_email, normalize_phone_number, validate_attachment_batch


def _api_token_is_valid(request):
    configured_token = getattr(settings, "CLIENT_TICKETS_API_TOKEN", "").strip()
    if not configured_token:
        return True
    return request.headers.get("X-Client-Ticket-Token", "").strip() == configured_token


def _request_payload(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body.") from exc
    return request.POST


def _payload_value(payload, *keys, default=None):
    for key in keys:
        if hasattr(payload, "get"):
            value = payload.get(key)
        else:
            value = payload[key] if key in payload else None
        if value not in (None, ""):
            return value
    return default


def _resolve_user(payload, *, email_keys, id_keys=(), label):
    user_id = _payload_value(payload, *id_keys)
    email = _payload_value(payload, *email_keys)
    queryset = User.objects.filter(is_active=True)
    user = None
    if user_id:
        user = queryset.filter(id=user_id).first()
    elif email:
        user = queryset.filter(email__iexact=email).first()
    if not user:
        raise ValueError(f"{label} not found.")
    return user


def _resolve_ticket_type(payload):
    type_id = _payload_value(payload, "ticket_type_id")
    type_name = _payload_value(payload, "ticket_type", "ticket_type_name")
    if type_id:
        return ClientTicketType.objects.filter(id=type_id, is_active=True).first()
    if type_name:
        return ClientTicketType.objects.filter(name__iexact=type_name, is_active=True).first()
    return None


def _resolve_department(payload, ticket_type=None):
    department_id = _payload_value(payload, "department_id")
    department_name = _payload_value(payload, "department")
    department = None
    if department_id:
        department = Department.objects.filter(id=department_id).first()
    elif department_name:
        department = Department.objects.filter(name__iexact=department_name).first()
    if not department and ticket_type and ticket_type.department_id:
        department = ticket_type.department
    return department


def _create_ticket_from_payload(payload, attachments=None, created_by=None):
    attachments = validate_attachment_batch(attachments or [])
    ticket_type = _resolve_ticket_type(payload)
    department = _resolve_department(payload, ticket_type=ticket_type)
    if not department:
        raise ValueError("Department is required.")

    assigned_to = _resolve_user(payload, email_keys=("assigned_to_email", "to_email"), id_keys=("assigned_to_id", "to_user_id"), label="Assigned to user")
    project_manager = _resolve_user(
        payload,
        email_keys=("project_manager_email", "pm_email"),
        id_keys=("project_manager_id", "pm_user_id"),
        label="Project manager",
    )

    requester_name = _payload_value(payload, "requester_name")
    requester_email = _payload_value(payload, "requester_email")
    requester_number = _payload_value(payload, "requester_number", "requester_phone")
    if not requester_name or not requester_email or not requester_number:
        raise ValueError("Requester name, email, and number are required.")

    client = upsert_client_contact(requester_name, requester_email, requester_number)

    ticket = ClientTicket(
        title=_payload_value(payload, "title"),
        description=_payload_value(payload, "description"),
        ticket_type=ticket_type,
        ticket_type_other=_payload_value(payload, "ticket_type_other", default=""),
        requester=client,
        requester_name=requester_name,
        requester_email=requester_email,
        requester_number=requester_number,
        assigned_to=assigned_to,
        project_manager=project_manager,
        created_by=created_by,
        user_type=_payload_value(payload, "user_type", default=ClientTicket.USER_TYPE_INTERNAL),
        source_system=_payload_value(payload, "source_system", default=ClientTicket.SOURCE_API if created_by is None else ClientTicket.SOURCE_MANUAL),
        priority=_payload_value(payload, "priority", default=ClientTicket.PRIORITY_MEDIUM),
        department=department,
        status=_payload_value(payload, "status", default=""),
    )
    if not ticket.title or not ticket.description:
        raise ValueError("Title and description are required.")
    ticket.save()

    initial_update = create_ticket_update(
        ticket,
        ClientTicketUpdate.ACTOR_INDITECH if created_by else ClientTicketUpdate.ACTOR_SYSTEM,
        message="Ticket created.",
        status=ticket.status,
        user=created_by,
        attachments=attachments,
    )
    notify_ticket_created(ticket)
    return ticket, initial_update


def _touch_inditech_activity(ticket, user):
    if not user.is_authenticated:
        return
    if user not in {ticket.assigned_to, ticket.project_manager}:
        return
    now = timezone.now()
    ticket.last_inditech_action_at = now
    ticket.updated_at = now
    ticket.save(update_fields=["last_inditech_action_at", "updated_at"])


@login_required
def dashboard(request):
    request.session["ticket_ui_mode"] = "external"
    return redirect("assigned_to_me")


@login_required
def ticket_list(request):
    request.session["ticket_ui_mode"] = "external"
    queryset = ClientTicket.objects.select_related("assigned_to", "project_manager", "department", "ticket_type").all()
    search = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    priority = request.GET.get("priority", "").strip()
    source_system = request.GET.get("source_system", "").strip()

    if search:
        queryset = queryset.filter(
            Q(ticket_number__icontains=search)
            | Q(title__icontains=search)
            | Q(requester_name__icontains=search)
            | Q(requester_email__icontains=search)
        )
    if status:
        queryset = queryset.filter(status=status)
    if priority:
        queryset = queryset.filter(priority=priority)
    if source_system:
        queryset = queryset.filter(source_system=source_system)

    context = {
        "tickets": queryset[:200],
        "search": search,
        "selected_status": status,
        "selected_priority": priority,
        "selected_source_system": source_system,
        "status_choices": ClientTicket.STATUS_CHOICES,
        "priority_choices": ClientTicket.PRIORITY_CHOICES,
        "source_choices": ClientTicket.SOURCE_SYSTEM_CHOICES,
    }
    return render(request, "client_tickets/ticket_list.html", context)


@login_required
def create_ticket(request):
    request.session["ticket_ui_mode"] = "external"
    return redirect("create_task")


@login_required
def ticket_detail(request, ticket_number):
    request.session["ticket_ui_mode"] = "external"
    ticket = get_object_or_404(
        ClientTicket.objects.select_related("assigned_to", "project_manager", "department", "ticket_type", "requester")
        .prefetch_related("attachments", "updates")
        .all(),
        ticket_number=ticket_number,
    )
    _touch_inditech_activity(ticket, request.user)

    inditech_form = ClientTicketInditechUpdateForm(ticket=ticket)
    client_form = ClientTicketClientUpdateForm(ticket=ticket)

    if request.method == "POST":
        if "submit_inditech_update" in request.POST:
            inditech_form = ClientTicketInditechUpdateForm(request.POST, request.FILES, ticket=ticket)
            client_form = ClientTicketClientUpdateForm(ticket=ticket)
            if inditech_form.is_valid():
                update = create_ticket_update(
                    ticket,
                    ClientTicketUpdate.ACTOR_INDITECH,
                    message=inditech_form.cleaned_data["message"],
                    status=inditech_form.cleaned_data["status"],
                    inditech_status=inditech_form.cleaned_data["inditech_status"],
                    user=request.user,
                    attachments=inditech_form.cleaned_data["attachments"],
                )
                notify_ticket_updated(ticket, update)
                messages.success(request, "Inditech update saved and emailed.")
                return redirect("client_tickets:ticket_detail", ticket.ticket_number)
        elif "submit_client_update" in request.POST:
            client_form = ClientTicketClientUpdateForm(request.POST, request.FILES, ticket=ticket)
            inditech_form = ClientTicketInditechUpdateForm(ticket=ticket)
            if client_form.is_valid():
                update = create_ticket_update(
                    ticket,
                    ClientTicketUpdate.ACTOR_CLIENT,
                    message=client_form.cleaned_data["message"],
                    client_status=client_form.cleaned_data["client_status"],
                    client=ticket.requester,
                    attachments=client_form.cleaned_data["attachments"],
                )
                notify_ticket_updated(ticket, update)
                messages.success(request, "Client update recorded and emailed.")
                return redirect("client_tickets:ticket_detail", ticket.ticket_number)

    context = {
        "ticket": ticket,
        "inditech_form": inditech_form,
        "client_form": client_form,
    }
    return render(request, "client_tickets/ticket_detail.html", context)


@csrf_exempt
@require_http_methods(["POST"])
def api_create_ticket(request):
    if not _api_token_is_valid(request):
        return JsonResponse({"success": False, "error": "Invalid API token."}, status=403)
    try:
        payload = _request_payload(request)
        attachments = request.FILES.getlist("attachments")
        ticket, _update = _create_ticket_from_payload(payload, attachments=attachments, created_by=None)
        return JsonResponse(
            {
                "success": True,
                "message": "Client ticket created successfully.",
                "ticket": ticket_to_dict(ticket),
            },
            status=201,
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)


@require_http_methods(["GET"])
def api_ticket_detail(request, ticket_number):
    ticket = get_object_or_404(ClientTicket.objects.prefetch_related("attachments", "updates"), ticket_number=ticket_number)
    if not _api_token_is_valid(request):
        requester_email = normalize_email(request.GET.get("requester_email"))
        requester_number = normalize_phone_number(request.GET.get("requester_number"))
        if requester_email != ticket.requester_email or requester_number != ticket.requester_number:
            return JsonResponse({"success": False, "error": "Not authorized for this ticket."}, status=403)

    payload = ticket_to_dict(ticket)
    payload["updates"] = [
        {
            "actor_type": update.actor_type,
            "message": update.message,
            "status": update.get_status_display() or "---------",
            "inditech_status": update.get_inditech_status_display() or "---------",
            "client_status": update.get_client_status_display() or "---------",
            "created_at": update.created_at.isoformat(),
        }
        for update in ticket.updates.all()
    ]
    return JsonResponse({"success": True, "ticket": payload})


@csrf_exempt
@require_http_methods(["POST"])
def api_inditech_update_ticket(request, ticket_number):
    if not _api_token_is_valid(request):
        return JsonResponse({"success": False, "error": "Invalid API token."}, status=403)
    ticket = get_object_or_404(ClientTicket, ticket_number=ticket_number)
    try:
        payload = _request_payload(request)
        updater = _resolve_user(payload, email_keys=("updated_by_email", "updater_email"), id_keys=("updated_by_id",), label="Updater")
        if _payload_value(payload, "title"):
            ticket.title = _payload_value(payload, "title")
        if _payload_value(payload, "description"):
            ticket.description = _payload_value(payload, "description")
        if _payload_value(payload, "priority"):
            ticket.priority = _payload_value(payload, "priority")
        if _payload_value(payload, "status"):
            ticket.status = _payload_value(payload, "status")
        if _payload_value(payload, "ticket_type_other"):
            ticket.ticket_type_other = _payload_value(payload, "ticket_type_other")
        ticket_type = _resolve_ticket_type(payload)
        if ticket_type:
            ticket.ticket_type = ticket_type
        department = _resolve_department(payload, ticket_type=ticket.ticket_type)
        if department:
            ticket.department = department
        ticket.save()
        attachments = validate_attachment_batch(
            request.FILES.getlist("attachments"),
            existing_count=ticket.attachments.count(),
        )

        update = create_ticket_update(
            ticket,
            ClientTicketUpdate.ACTOR_INDITECH,
            message=_payload_value(payload, "message", default=""),
            status=_payload_value(payload, "status", default=""),
            inditech_status=_payload_value(payload, "inditech_status", default=""),
            user=updater,
            attachments=attachments,
        )
        notify_ticket_updated(ticket, update)
        return JsonResponse({"success": True, "ticket": ticket_to_dict(ticket)})
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def api_client_update_ticket(request, ticket_number):
    ticket = get_object_or_404(ClientTicket, ticket_number=ticket_number)
    try:
        payload = _request_payload(request)
        requester_email = normalize_email(_payload_value(payload, "requester_email"))
        requester_number = normalize_phone_number(_payload_value(payload, "requester_number", "requester_phone"))
        if not _api_token_is_valid(request):
            if requester_email != ticket.requester_email or requester_number != ticket.requester_number:
                return JsonResponse({"success": False, "error": "Requester credentials do not match this ticket."}, status=403)
        attachments = validate_attachment_batch(
            request.FILES.getlist("attachments"),
            existing_count=ticket.attachments.count(),
        )
        update = create_ticket_update(
            ticket,
            ClientTicketUpdate.ACTOR_CLIENT,
            message=_payload_value(payload, "message", default=""),
            client_status=_payload_value(payload, "client_status", default=""),
            client=ticket.requester,
            attachments=attachments,
        )
        notify_ticket_updated(ticket, update)
        return JsonResponse({"success": True, "ticket": ticket_to_dict(ticket)})
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
