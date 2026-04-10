from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify

from .models import ClientContact, ClientTicket, ClientTicketAttachment, ClientTicketUpdate
from .utils import build_absolute_link, get_base_url, normalize_email, normalize_phone_number, priority_color


def upsert_client_contact(name, email, phone_number):
    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone_number(phone_number)
    client, created = ClientContact.objects.get_or_create(
        email=normalized_email,
        phone_number=normalized_phone,
        defaults={"name": (name or "").strip()},
    )
    if not created and name and client.name != name.strip():
        client.name = name.strip()
        client.updated_at = timezone.now()
        client.save(update_fields=["name", "updated_at"])
    return client


def derive_ticket_status(ticket):
    if ticket.status in {ClientTicket.STATUS_CANCELLED, ClientTicket.STATUS_AUTO_CLOSED}:
        return ticket.status
    if ticket.inditech_status in {ClientTicket.PARTICIPANT_COMPLETED, ClientTicket.PARTICIPANT_CLOSED}:
        if ticket.client_status in {ClientTicket.PARTICIPANT_COMPLETED, ClientTicket.PARTICIPANT_CLOSED}:
            return ClientTicket.STATUS_CLOSED
        return ClientTicket.STATUS_RESOLVED
    if ticket.inditech_status == ClientTicket.PARTICIPANT_NEEDS_CLARIFICATION:
        return ClientTicket.STATUS_WAITING_FOR_CLIENT
    if ticket.client_status == ClientTicket.PARTICIPANT_NEEDS_CLARIFICATION:
        return ClientTicket.STATUS_WAITING_FOR_INDITECH
    if ticket.inditech_status == ClientTicket.PARTICIPANT_IN_PROGRESS or ticket.client_status == ClientTicket.PARTICIPANT_IN_PROGRESS:
        return ClientTicket.STATUS_IN_PROGRESS
    return ticket.status or ClientTicket.STATUS_OPEN


def stakeholder_emails(ticket, extra=None, exclude=None, include_created_by=False):
    recipients = []
    if ticket.requester_email:
        recipients.append(ticket.requester_email)
    if ticket.assigned_to and ticket.assigned_to.email:
        recipients.append(ticket.assigned_to.email)
    if ticket.project_manager and ticket.project_manager.email:
        recipients.append(ticket.project_manager.email)
    if include_created_by and ticket.created_by and ticket.created_by.email:
        recipients.append(ticket.created_by.email)
    recipients.extend(extra or [])
    excluded = {normalize_email(email) for email in (exclude or []) if email}
    deduped = []
    seen = set()
    for email in recipients:
        normalized = normalize_email(email)
        if not normalized or normalized in seen or normalized in excluded:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def attachment_items(ticket):
    items = []
    for attachment in ticket.attachments.all():
        items.append(
            {
                "id": attachment.id,
                "name": attachment.filename,
                "role": attachment.get_uploaded_by_role_display(),
                "role_code": attachment.uploaded_by_role,
                "url": build_absolute_link(attachment.file.url),
                "uploaded_at": attachment.uploaded_at.isoformat(),
            }
        )
    return items


def department_code(department):
    if not department:
        return ""
    return slugify(department.name or "").replace("-", "_").upper()


def display_or_blank(value, default="---------"):
    return value or default


def user_display_name(user):
    if not user:
        return ""
    return user.get_full_name() or user.username


def user_to_lookup_dict(user):
    profile = getattr(user, "userprofile", None)
    department = getattr(profile, "department", None)
    return {
        "id": user.id,
        "full_name": user_display_name(user),
        "email": user.email or "",
        "department_id": department.id if department else None,
        "department_name": department.name if department else "",
        "is_active": user.is_active,
    }


def department_to_lookup_dict(department):
    manager = getattr(department, "manager", None)
    return {
        "id": department.id,
        "name": department.name,
        "code": department_code(department),
        "manager_id": manager.id if manager else None,
        "manager_name": user_display_name(manager),
        "manager_email": manager.email if manager and manager.email else "",
        "is_active": True,
    }


def department_manager_to_lookup_dict(department):
    manager = getattr(department, "manager", None)
    return {
        "department_id": department.id,
        "department_name": department.name,
        "department_code": department_code(department),
        "manager_id": manager.id if manager else None,
        "manager_name": user_display_name(manager),
        "manager_email": manager.email if manager and manager.email else "",
    }


def ticket_update_to_dict(update):
    return {
        "id": update.id,
        "actor_type": update.actor_type,
        "actor_label": update.get_actor_type_display(),
        "message": update.message,
        "status": display_or_blank(update.get_status_display()),
        "status_code": update.status or "",
        "inditech_status": display_or_blank(update.get_inditech_status_display()),
        "inditech_status_code": update.inditech_status or "",
        "client_status": display_or_blank(update.get_client_status_display()),
        "client_status_code": update.client_status or "",
        "created_at": update.created_at.isoformat(),
        "attachments": [
            {
                "id": attachment.id,
                "name": attachment.filename,
                "role": attachment.get_uploaded_by_role_display(),
                "role_code": attachment.uploaded_by_role,
                "url": build_absolute_link(attachment.file.url),
                "uploaded_at": attachment.uploaded_at.isoformat(),
            }
            for attachment in update.attachments.all()
        ],
    }


def ticket_to_dict(ticket):
    assigned_to = user_display_name(ticket.assigned_to)
    project_manager = user_display_name(ticket.project_manager)
    return {
        "ticket_number": ticket.ticket_number,
        "external_reference": ticket.external_reference,
        "title": ticket.title,
        "description": ticket.description,
        "ticket_type": ticket.ticket_type_label,
        "ticket_type_id": ticket.ticket_type_id,
        "ticket_type_other": ticket.ticket_type_other,
        "requester_name": ticket.requester_name,
        "requester_email": ticket.requester_email,
        "requester_number": ticket.requester_number,
        "assigned_to": assigned_to,
        "assigned_to_id": ticket.assigned_to_id,
        "assigned_to_email": ticket.assigned_to.email if ticket.assigned_to and ticket.assigned_to.email else "",
        "project_manager": project_manager,
        "project_manager_id": ticket.project_manager_id,
        "project_manager_email": (
            ticket.project_manager.email if ticket.project_manager and ticket.project_manager.email else ""
        ),
        "user_type": ticket.get_user_type_display(),
        "user_type_code": ticket.user_type,
        "source_system": ticket.get_source_system_display(),
        "source_system_code": ticket.source_system,
        "priority": ticket.get_priority_display(),
        "priority_code": ticket.priority,
        "department": ticket.department.name if ticket.department else "",
        "department_id": ticket.department_id,
        "department_code": department_code(ticket.department),
        "status": display_or_blank(ticket.get_status_display()),
        "status_code": ticket.status or "",
        "inditech_status": display_or_blank(ticket.get_inditech_status_display()),
        "inditech_status_code": ticket.inditech_status or "",
        "client_status": display_or_blank(ticket.get_client_status_display()),
        "client_status_code": ticket.client_status or "",
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "ticket_url": build_absolute_link(ticket.get_absolute_url()),
        "attachments": attachment_items(ticket),
    }


def ticket_summary_to_dict(ticket):
    return {
        "ticket_number": ticket.ticket_number,
        "external_reference": ticket.external_reference,
        "title": ticket.title,
        "status_code": ticket.status or "",
        "status_label": display_or_blank(ticket.get_status_display()),
        "priority_code": ticket.priority,
        "priority_label": ticket.get_priority_display(),
        "assigned_to_email": ticket.assigned_to.email if ticket.assigned_to and ticket.assigned_to.email else "",
        "project_manager_email": (
            ticket.project_manager.email if ticket.project_manager and ticket.project_manager.email else ""
        ),
        "updated_at": ticket.updated_at.isoformat(),
        "ticket_url": build_absolute_link(ticket.get_absolute_url()),
    }


def send_ticket_email(subject, intro, ticket, recipients, update=None, template_name="client_tickets/emails/ticket_notification.html", extra_context=None):
    to = stakeholder_emails(ticket, extra=recipients)
    if not to:
        return False
    context = {
        "subject": subject,
        "intro": intro,
        "ticket": ticket,
        "ticket_url": build_absolute_link(ticket.get_absolute_url()),
        "attachments": attachment_items(ticket),
        "update": update,
        "priority_color": priority_color(ticket.priority),
        "base_url": get_base_url(),
    }
    if extra_context:
        context.update(extra_context)
    html_body = render_to_string(template_name, context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=f"{intro}\nTicket: {ticket.ticket_number}",
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@yourdomain.com"),
        to=to,
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
    return True


def resolve_uploaded_by_role(ticket, actor_type, user=None):
    if actor_type == ClientTicketUpdate.ACTOR_CLIENT:
        return ClientTicketAttachment.UPLOADER_CLIENT
    if user and ticket.project_manager_id == user.id:
        return ClientTicketAttachment.UPLOADER_PM
    return ClientTicketAttachment.UPLOADER_INDITECH


def save_ticket_attachments(ticket, attachments, uploaded_by_role, user=None, update=None):
    saved = []
    for upload in attachments or []:
        saved.append(
            ClientTicketAttachment.objects.create(
                ticket=ticket,
                update=update,
                file=upload,
                uploaded_by_role=uploaded_by_role,
                uploaded_by=user,
            )
        )
    return saved


def create_ticket_update(
    ticket,
    actor_type,
    *,
    message="",
    status="",
    inditech_status="",
    client_status="",
    user=None,
    client=None,
    attachments=None,
):
    now = timezone.now()
    if status:
        ticket.status = status
    if inditech_status:
        ticket.inditech_status = inditech_status
    if client_status:
        ticket.client_status = client_status

    if actor_type == ClientTicketUpdate.ACTOR_INDITECH:
        ticket.last_inditech_action_at = now
    elif actor_type == ClientTicketUpdate.ACTOR_CLIENT:
        ticket.last_client_action_at = now

    if ticket.inditech_status in {ClientTicket.PARTICIPANT_COMPLETED, ClientTicket.PARTICIPANT_CLOSED} and not ticket.inditech_completed_at:
        ticket.inditech_completed_at = now
    if ticket.client_status in {ClientTicket.PARTICIPANT_COMPLETED, ClientTicket.PARTICIPANT_CLOSED} and not ticket.client_completed_at:
        ticket.client_completed_at = now

    if not status:
        ticket.status = derive_ticket_status(ticket)

    if ticket.status in {ClientTicket.STATUS_CLOSED, ClientTicket.STATUS_AUTO_CLOSED} and not ticket.closed_at:
        ticket.closed_at = now
    ticket.updated_at = now
    ticket.save()

    update = ClientTicketUpdate.objects.create(
        ticket=ticket,
        actor_type=actor_type,
        user=user,
        client=client,
        message=(message or "").strip(),
        status=ticket.status,
        inditech_status=ticket.inditech_status,
        client_status=ticket.client_status,
    )
    uploaded_by_role = resolve_uploaded_by_role(ticket, actor_type, user=user)
    save_ticket_attachments(ticket, attachments, uploaded_by_role=uploaded_by_role, user=user, update=update)
    return update


def notify_ticket_created(ticket):
    return send_ticket_email(
        subject=f"Client Ticket Created: {ticket.ticket_number} - {ticket.title}",
        intro="A new client ticket has been created. All the current details are below for action.",
        ticket=ticket,
        recipients=stakeholder_emails(ticket, include_created_by=True),
    )


def notify_ticket_updated(ticket, update):
    actor_label = update.get_actor_type_display()
    return send_ticket_email(
        subject=f"Client Ticket Updated: {ticket.ticket_number} - {ticket.title}",
        intro=f"{actor_label} updated this client ticket. The latest status and details are below.",
        ticket=ticket,
        recipients=stakeholder_emails(ticket, include_created_by=True),
        update=update,
    )


def notify_ticket_auto_closed(ticket):
    return send_ticket_email(
        subject=f"Client Ticket Auto Closed: {ticket.ticket_number} - {ticket.title}",
        intro="This ticket has been auto closed because the Inditech side marked it completed and no client closure came in for 7 days.",
        ticket=ticket,
        recipients=stakeholder_emails(ticket, include_created_by=True),
    )


def send_unchecked_ticket_reminders():
    now = timezone.now()
    threshold = now - timedelta(hours=24)
    sent_count = 0
    tickets = (
        ClientTicket.objects.select_related("assigned_to", "project_manager", "department", "ticket_type")
        .prefetch_related("attachments")
        .filter(created_at__lte=threshold, last_inditech_action_at__isnull=True)
        .exclude(status__in=[ClientTicket.STATUS_CLOSED, ClientTicket.STATUS_AUTO_CLOSED, ClientTicket.STATUS_CANCELLED])
    )
    for ticket in tickets:
        if ticket.last_reminder_sent_at and ticket.last_reminder_sent_at >= now - timedelta(hours=24):
            continue
        recipients = []
        if ticket.assigned_to and ticket.assigned_to.email:
            recipients.append(ticket.assigned_to.email)
        if ticket.project_manager and ticket.project_manager.email:
            recipients.append(ticket.project_manager.email)
        if not recipients:
            continue
        send_ticket_email(
            subject=f"Reminder: Client Ticket Awaiting Inditech Action ({ticket.ticket_number})",
            intro="This ticket has not been checked or updated by the Inditech team within 24 hours of being raised.",
            ticket=ticket,
            recipients=recipients,
        )
        ticket.last_reminder_sent_at = now
        ticket.updated_at = now
        ticket.save(update_fields=["last_reminder_sent_at", "updated_at"])
        sent_count += 1
    return sent_count


def auto_close_stale_tickets():
    now = timezone.now()
    threshold = now - timedelta(days=7)
    closed_count = 0
    tickets = (
        ClientTicket.objects.select_related("assigned_to", "project_manager")
        .prefetch_related("attachments")
        .filter(inditech_completed_at__lte=threshold, auto_closed_at__isnull=True)
        .exclude(status__in=[ClientTicket.STATUS_CLOSED, ClientTicket.STATUS_AUTO_CLOSED, ClientTicket.STATUS_CANCELLED])
    )
    tickets = tickets.exclude(client_status__in=[ClientTicket.PARTICIPANT_COMPLETED, ClientTicket.PARTICIPANT_CLOSED])
    for ticket in tickets:
        ticket.status = ClientTicket.STATUS_AUTO_CLOSED
        ticket.auto_closed_at = now
        ticket.closed_at = now
        ticket.updated_at = now
        ticket.save(update_fields=["status", "auto_closed_at", "closed_at", "updated_at"])
        ClientTicketUpdate.objects.create(
            ticket=ticket,
            actor_type=ClientTicketUpdate.ACTOR_SYSTEM,
            message="Ticket auto closed because the client did not close it within 7 days of Inditech completion.",
            status=ticket.status,
            inditech_status=ticket.inditech_status,
            client_status=ticket.client_status,
        )
        notify_ticket_auto_closed(ticket)
        closed_count += 1
    return closed_count


def send_daily_summary_emails():
    active_tickets = (
        ClientTicket.objects.select_related("assigned_to", "project_manager", "department", "ticket_type")
        .prefetch_related("attachments")
        .exclude(status__in=[ClientTicket.STATUS_CLOSED, ClientTicket.STATUS_AUTO_CLOSED, ClientTicket.STATUS_CANCELLED])
    )
    user_ids = set()
    for ticket in active_tickets:
        if ticket.assigned_to_id:
            user_ids.add(ticket.assigned_to_id)
        if ticket.project_manager_id:
            user_ids.add(ticket.project_manager_id)

    sent_count = 0
    now = timezone.now()
    for user in User.objects.filter(id__in=user_ids).order_by("first_name", "username"):
        if not user.email:
            continue
        relevant_tickets = active_tickets.filter(Q(assigned_to=user) | Q(project_manager=user)).distinct().order_by(
            "-updated_at"
        )
        if not relevant_tickets.exists():
            continue

        ticket_rows = []
        for ticket in relevant_tickets:
            ticket_rows.append(
                {
                    "ticket": ticket,
                    "priority_color": priority_color(ticket.priority),
                }
            )

        context = {
            "user": user,
            "generated_at": now,
            "ticket_rows": ticket_rows,
            "summary": {
                "pending_count": relevant_tickets.count(),
                "high_priority_count": relevant_tickets.filter(
                    priority__in=[ClientTicket.PRIORITY_HIGH, ClientTicket.PRIORITY_URGENT]
                ).count(),
                "waiting_for_client_count": relevant_tickets.filter(
                    status=ClientTicket.STATUS_WAITING_FOR_CLIENT
                ).count(),
                "waiting_for_inditech_count": relevant_tickets.filter(
                    status=ClientTicket.STATUS_WAITING_FOR_INDITECH
                ).count(),
                "resolved_count": relevant_tickets.filter(status=ClientTicket.STATUS_RESOLVED).count(),
            },
        }
        html_body = render_to_string("client_tickets/emails/daily_summary.html", context)
        message = EmailMultiAlternatives(
            subject=f"Client Tickets Daily Summary - {now.strftime('%d %b %Y')}",
            body="Client tickets daily summary",
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@yourdomain.com"),
            to=[user.email],
        )
        message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
        sent_count += 1
    return sent_count
