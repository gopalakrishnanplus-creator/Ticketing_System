import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from task_app.models import Department

from .forms import ClientTicketClientUpdateForm, ClientTicketForm, ClientTicketInditechUpdateForm
from .models import ClientContact, ClientTicket, ClientTicketType, ClientTicketUpdate
from .services import (
    attachment_items as build_client_attachment_items,
    create_ticket_update,
    notify_ticket_created,
    notify_ticket_updated,
    send_daily_summary_emails,
    send_unchecked_ticket_reminders,
    ticket_summary_to_dict,
    ticket_to_dict,
    ticket_update_to_dict,
    user_to_lookup_dict,
    upsert_client_contact,
    auto_close_stale_tickets,
    department_code,
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


def _payload_includes(payload, *keys):
    for key in keys:
        if hasattr(payload, "keys") and key in payload:
            return True
        if not hasattr(payload, "keys") and key in payload:
            return True
    return False


def _json_error(message, *, status=400, code="bad_request", details=None):
    payload = {
        "success": False,
        "error": message,
        "error_code": code,
    }
    if details is not None:
        payload["details"] = details
    return JsonResponse(payload, status=status)


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


def _validate_external_reference(source_system, external_reference, *, current_ticket=None):
    reference = (external_reference or "").strip()
    if not reference:
        return ""
    queryset = ClientTicket.objects.filter(source_system=source_system, external_reference__iexact=reference)
    if current_ticket is not None:
        queryset = queryset.exclude(pk=current_ticket.pk)
    if queryset.exists():
        raise ValueError("External reference already exists for this source system.")
    return reference


def _parse_positive_int(value, *, default, minimum=1, maximum=None):
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid pagination value.") from exc
    if parsed < minimum:
        parsed = minimum
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def _lookup_users_queryset():
    return User.objects.filter(is_active=True).select_related("userprofile__department").order_by("first_name", "username")


def _coerce_choice(value, choices, *, label, allow_blank=False):
    if value in (None, ""):
        if allow_blank:
            return ""
        raise ValueError(f"{label} is required.")

    normalized = str(value).strip()
    if not normalized:
        if allow_blank:
            return ""
        raise ValueError(f"{label} is required.")

    for code, display in choices:
        if normalized.lower() == str(code).lower() or normalized.lower() == str(display).lower():
            return code

    raise ValueError(f"Invalid {label}.")


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
    source_system = _coerce_choice(
        _payload_value(
            payload,
            "source_system",
            default=ClientTicket.SOURCE_API if created_by is None else ClientTicket.SOURCE_MANUAL,
        ),
        ClientTicket.SOURCE_SYSTEM_CHOICES,
        label="Source system",
    )
    user_type = _coerce_choice(
        _payload_value(payload, "user_type", default=ClientTicket.USER_TYPE_INTERNAL),
        ClientTicket.USER_TYPE_CHOICES,
        label="User type",
    )
    priority = _coerce_choice(
        _payload_value(payload, "priority", default=ClientTicket.PRIORITY_MEDIUM),
        ClientTicket.PRIORITY_CHOICES,
        label="Priority",
    )
    status = _coerce_choice(
        _payload_value(payload, "status", default=""),
        ClientTicket.STATUS_CHOICES,
        label="Status",
        allow_blank=True,
    )
    external_reference = _validate_external_reference(
        source_system,
        _payload_value(payload, "external_reference", default=""),
    )

    ticket = ClientTicket(
        external_reference=external_reference,
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
        user_type=user_type,
        source_system=source_system,
        priority=priority,
        department=department,
        status=status,
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
        .prefetch_related("attachments", "updates__attachments")
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
        "mail_attachments": build_client_attachment_items(ticket),
    }
    return render(request, "client_tickets/ticket_detail.html", context)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_tickets(request):
    if request.method == "POST":
        if not _api_token_is_valid(request):
            return _json_error("Invalid API token.", status=403, code="auth_failed")
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
        except ValidationError as exc:
            return _json_error("; ".join(exc.messages), code="validation_error")
        except ValueError as exc:
            return _json_error(str(exc), code="validation_error")

    if not _api_token_is_valid(request):
        return _json_error("Invalid API token.", status=403, code="auth_failed")

    queryset = ClientTicket.objects.select_related("assigned_to", "project_manager", "department", "ticket_type").all()
    source_system = request.GET.get("source_system", "").strip()
    status = request.GET.get("status", "").strip()
    updated_after = request.GET.get("updated_after", "").strip()

    try:
        if source_system:
            queryset = queryset.filter(
                source_system=_coerce_choice(
                    source_system,
                    ClientTicket.SOURCE_SYSTEM_CHOICES,
                    label="Source system",
                )
            )
        if status:
            queryset = queryset.filter(
                status=_coerce_choice(
                    status,
                    ClientTicket.STATUS_CHOICES,
                    label="Status",
                    allow_blank=True,
                )
            )
        if updated_after:
            parsed_updated_after = parse_datetime(updated_after)
            if parsed_updated_after is None:
                raise ValueError("Invalid updated_after timestamp.")
            if timezone.is_naive(parsed_updated_after):
                parsed_updated_after = timezone.make_aware(parsed_updated_after, timezone.get_current_timezone())
            queryset = queryset.filter(updated_at__gt=parsed_updated_after)

        page = _parse_positive_int(request.GET.get("page"), default=1)
        page_size = _parse_positive_int(request.GET.get("page_size"), default=50, maximum=200)
    except ValueError as exc:
        return _json_error(str(exc), code="validation_error")

    queryset = queryset.order_by("updated_at", "id")
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page)

    next_url = None
    if page_obj.has_next():
        params = request.GET.copy()
        params["page"] = page_obj.next_page_number()
        next_url = request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

    return JsonResponse(
        {
            "success": True,
            "count": paginator.count,
            "next": next_url,
            "results": [ticket_summary_to_dict(ticket) for ticket in page_obj.object_list],
        }
    )


@require_http_methods(["GET"])
def api_ticket_detail(request, ticket_number):
    ticket = get_object_or_404(
        ClientTicket.objects.select_related("assigned_to", "project_manager", "department", "ticket_type")
        .prefetch_related("attachments", "updates__attachments"),
        ticket_number=ticket_number,
    )
    if not _api_token_is_valid(request):
        requester_email = normalize_email(request.GET.get("requester_email"))
        requester_number = normalize_phone_number(request.GET.get("requester_number"))
        if requester_email != ticket.requester_email or requester_number != ticket.requester_number:
            return _json_error("Not authorized for this ticket.", status=403, code="auth_failed")

    payload = ticket_to_dict(ticket)
    payload["updates"] = [ticket_update_to_dict(update) for update in ticket.updates.all().order_by("created_at", "id")]
    return JsonResponse({"success": True, "ticket": payload})


@require_http_methods(["GET"])
def api_lookup_departments(request):
    if not _api_token_is_valid(request):
        return _json_error("Invalid API token.", status=403, code="auth_failed")

    departments = Department.objects.select_related("manager").all().order_by("name")
    return JsonResponse(
        {
            "success": True,
            "departments": [
                {
                    "id": department.id,
                    "name": department.name,
                    "code": department_code(department),
                    "is_active": True,
                }
                for department in departments
            ],
        }
    )


@require_http_methods(["GET"])
def api_lookup_ticket_types(request):
    if not _api_token_is_valid(request):
        return _json_error("Invalid API token.", status=403, code="auth_failed")

    queryset = ClientTicketType.objects.select_related("department").all().order_by("name")
    department_id = request.GET.get("department_id")
    is_active = request.GET.get("is_active", "").strip().lower()

    if department_id:
        queryset = queryset.filter(department_id=department_id)
    if is_active in {"1", "true", "yes", "on"}:
        queryset = queryset.filter(is_active=True)

    return JsonResponse(
        {
            "success": True,
            "ticket_types": [
                {
                    "id": ticket_type.id,
                    "name": ticket_type.name,
                    "department_id": ticket_type.department_id,
                    "department_name": ticket_type.department.name if ticket_type.department else "",
                    "is_active": ticket_type.is_active,
                }
                for ticket_type in queryset
            ],
        }
    )


@require_http_methods(["GET"])
def api_lookup_users(request):
    if not _api_token_is_valid(request):
        return _json_error("Invalid API token.", status=403, code="auth_failed")

    queryset = _lookup_users_queryset()
    department_id = request.GET.get("department_id")
    is_active = request.GET.get("is_active", "").strip().lower()

    if department_id:
        queryset = queryset.filter(userprofile__department_id=department_id)
    if is_active in {"0", "false", "no", "off"}:
        queryset = User.objects.none()

    return JsonResponse(
        {
            "success": True,
            "users": [user_to_lookup_dict(user) for user in queryset],
        }
    )


@require_http_methods(["GET"])
def api_lookup_project_managers(request):
    if not _api_token_is_valid(request):
        return _json_error("Invalid API token.", status=403, code="auth_failed")

    queryset = _lookup_users_queryset()
    is_active = request.GET.get("is_active", "").strip().lower()
    if is_active in {"0", "false", "no", "off"}:
        queryset = User.objects.none()

    return JsonResponse(
        {
            "success": True,
            "project_managers": [
                {
                    "id": user.id,
                    "full_name": user.get_full_name() or user.username,
                    "email": user.email or "",
                    "is_active": user.is_active,
                }
                for user in queryset
            ],
        }
    )


@require_http_methods(["GET"])
def api_ticket_by_external_reference(request):
    if not _api_token_is_valid(request):
        return _json_error("Invalid API token.", status=403, code="auth_failed")

    external_reference = (request.GET.get("external_reference") or "").strip()
    source_system = request.GET.get("source_system", "").strip()
    if not external_reference:
        return _json_error("external_reference is required.", code="validation_error")

    queryset = ClientTicket.objects.select_related("assigned_to", "project_manager", "department", "ticket_type").filter(
        external_reference__iexact=external_reference
    )
    if source_system:
        try:
            queryset = queryset.filter(
                source_system=_coerce_choice(
                    source_system,
                    ClientTicket.SOURCE_SYSTEM_CHOICES,
                    label="Source system",
                )
            )
        except ValueError as exc:
            return _json_error(str(exc), code="validation_error")

    ticket = queryset.first()
    if not ticket:
        return _json_error("Ticket not found.", status=404, code="not_found")

    return JsonResponse({"success": True, "ticket": ticket_summary_to_dict(ticket)})


@csrf_exempt
@require_http_methods(["POST"])
def api_inditech_update_ticket(request, ticket_number):
    if not _api_token_is_valid(request):
        return _json_error("Invalid API token.", status=403, code="auth_failed")

    ticket = get_object_or_404(
        ClientTicket.objects.select_related("assigned_to", "project_manager", "department", "ticket_type").prefetch_related("attachments"),
        ticket_number=ticket_number,
    )
    try:
        payload = _request_payload(request)
        updater = _resolve_user(
            payload,
            email_keys=("updated_by_email", "updater_email"),
            id_keys=("updated_by_id",),
            label="Updater",
        )
        status = _coerce_choice(
            _payload_value(payload, "status", default=""),
            ClientTicket.STATUS_CHOICES,
            label="Status",
            allow_blank=True,
        )
        inditech_status = _coerce_choice(
            _payload_value(payload, "inditech_status", default=""),
            ClientTicket.PARTICIPANT_STATUS_CHOICES,
            label="Inditech status",
            allow_blank=True,
        )

        if _payload_includes(payload, "title"):
            ticket.title = (_payload_value(payload, "title", default="") or "").strip()
        if _payload_includes(payload, "description"):
            ticket.description = (_payload_value(payload, "description", default="") or "").strip()
        if _payload_includes(payload, "priority"):
            ticket.priority = _coerce_choice(
                _payload_value(payload, "priority"),
                ClientTicket.PRIORITY_CHOICES,
                label="Priority",
            )
        if _payload_includes(payload, "status"):
            ticket.status = status
        if _payload_includes(payload, "ticket_type_other"):
            ticket.ticket_type_other = (_payload_value(payload, "ticket_type_other", default="") or "").strip()
        if _payload_includes(payload, "ticket_type", "ticket_type_name", "ticket_type_id"):
            ticket_type = _resolve_ticket_type(payload)
            if not ticket_type:
                return _json_error("Ticket type not found.", code="validation_error")
            ticket.ticket_type = ticket_type
        if _payload_includes(payload, "department", "department_id"):
            department = _resolve_department(payload, ticket_type=ticket.ticket_type)
            if not department:
                return _json_error("Department not found.", code="validation_error")
            ticket.department = department
        if _payload_includes(payload, "assigned_to_email", "assigned_to_id", "to_email", "to_user_id"):
            ticket.assigned_to = _resolve_user(
                payload,
                email_keys=("assigned_to_email", "to_email"),
                id_keys=("assigned_to_id", "to_user_id"),
                label="Assigned to user",
            )
        if _payload_includes(payload, "project_manager_email", "project_manager_id", "pm_email", "pm_user_id"):
            ticket.project_manager = _resolve_user(
                payload,
                email_keys=("project_manager_email", "pm_email"),
                id_keys=("project_manager_id", "pm_user_id"),
                label="Project manager",
            )
        if _payload_includes(payload, "external_reference"):
            ticket.external_reference = _validate_external_reference(
                ticket.source_system,
                _payload_value(payload, "external_reference", default=""),
                current_ticket=ticket,
            )
        if not ticket.title or not ticket.description:
            raise ValueError("Title and description are required.")

        ticket.save()
        attachments = validate_attachment_batch(
            request.FILES.getlist("attachments"),
            existing_count=ticket.attachments.count(),
        )

        update = create_ticket_update(
            ticket,
            ClientTicketUpdate.ACTOR_INDITECH,
            message=_payload_value(payload, "message", default=""),
            status=status,
            inditech_status=inditech_status,
            user=updater,
            attachments=attachments,
        )
        notify_ticket_updated(ticket, update)
        return JsonResponse({"success": True, "ticket": ticket_to_dict(ticket)})
    except ValidationError as exc:
        return _json_error("; ".join(exc.messages), code="validation_error")
    except ValueError as exc:
        return _json_error(str(exc), code="validation_error")


@csrf_exempt
@require_http_methods(["POST"])
def api_client_update_ticket(request, ticket_number):
    ticket = get_object_or_404(ClientTicket.objects.prefetch_related("attachments"), ticket_number=ticket_number)
    try:
        payload = _request_payload(request)
        requester_email = normalize_email(_payload_value(payload, "requester_email"))
        requester_number = normalize_phone_number(_payload_value(payload, "requester_number", "requester_phone"))
        if not _api_token_is_valid(request):
            if requester_email != ticket.requester_email or requester_number != ticket.requester_number:
                return _json_error(
                    "Requester credentials do not match this ticket.",
                    status=403,
                    code="auth_failed",
                )
        attachments = validate_attachment_batch(
            request.FILES.getlist("attachments"),
            existing_count=ticket.attachments.count(),
        )
        client_status = _coerce_choice(
            _payload_value(payload, "client_status", default=""),
            ClientTicket.PARTICIPANT_STATUS_CHOICES,
            label="Client status",
            allow_blank=True,
        )
        update = create_ticket_update(
            ticket,
            ClientTicketUpdate.ACTOR_CLIENT,
            message=_payload_value(payload, "message", default=""),
            client_status=client_status,
            client=ticket.requester,
            attachments=attachments,
        )
        notify_ticket_updated(ticket, update)
        return JsonResponse({"success": True, "ticket": ticket_to_dict(ticket)})
    except ValidationError as exc:
        return _json_error("; ".join(exc.messages), code="validation_error")
    except ValueError as exc:
        return _json_error(str(exc), code="validation_error")
