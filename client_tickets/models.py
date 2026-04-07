import os
import uuid

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from task_app.models import Department

from .utils import normalize_email, normalize_phone_number


def client_ticket_upload_to(instance, filename):
    ticket_number = instance.ticket.ticket_number if instance.ticket_id else "unassigned"
    return os.path.join("client_ticket_attachments", ticket_number, filename)


class ClientContact(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone_number = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "email"]
        constraints = [
            models.UniqueConstraint(fields=["email", "phone_number"], name="unique_client_contact_email_phone")
        ]

    def save(self, *args, **kwargs):
        self.email = normalize_email(self.email)
        self.phone_number = normalize_phone_number(self.phone_number)
        self.name = (self.name or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} <{self.email}>"


class ClientTicketType(models.Model):
    name = models.CharField(max_length=150, unique=True)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ClientTicket(models.Model):
    USER_TYPE_INTERNAL = "internal"
    USER_TYPE_CLIENT = "client"
    USER_TYPE_AGENCY = "agency"
    USER_TYPE_VENDOR = "vendor"
    USER_TYPE_CHOICES = [
        (USER_TYPE_INTERNAL, "Internal"),
        (USER_TYPE_CLIENT, "Client"),
        (USER_TYPE_AGENCY, "Agency"),
        (USER_TYPE_VENDOR, "Vendor"),
    ]

    SOURCE_MANUAL = "manual"
    SOURCE_PM_DASHBOARD = "pm_dashboard"
    SOURCE_CAMPAIGN = "campaign_management"
    SOURCE_API = "api"
    SOURCE_INDITECH = "inditech_ticketing"
    SOURCE_SYSTEM_CHOICES = [
        (SOURCE_MANUAL, "Manual"),
        (SOURCE_PM_DASHBOARD, "PM Dashboard"),
        (SOURCE_CAMPAIGN, "Campaign Management"),
        (SOURCE_API, "API"),
        (SOURCE_INDITECH, "Inditech Ticketing"),
    ]

    PRIORITY_LOW = "low"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_HIGH = "high"
    PRIORITY_URGENT = "urgent"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_WAITING_FOR_CLIENT = "waiting_for_client"
    STATUS_WAITING_FOR_INDITECH = "waiting_for_inditech"
    STATUS_RESOLVED = "resolved"
    STATUS_CLOSED = "closed"
    STATUS_AUTO_CLOSED = "auto_closed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        ("", "---------"),
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_WAITING_FOR_CLIENT, "Waiting For Client"),
        (STATUS_WAITING_FOR_INDITECH, "Waiting For Inditech"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_CLOSED, "Closed"),
        (STATUS_AUTO_CLOSED, "Auto Closed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    PARTICIPANT_PENDING = "pending"
    PARTICIPANT_IN_PROGRESS = "in_progress"
    PARTICIPANT_NEEDS_CLARIFICATION = "needs_clarification"
    PARTICIPANT_COMPLETED = "completed"
    PARTICIPANT_CLOSED = "closed"
    PARTICIPANT_STATUS_CHOICES = [
        ("", "---------"),
        (PARTICIPANT_PENDING, "Pending"),
        (PARTICIPANT_IN_PROGRESS, "In Progress"),
        (PARTICIPANT_NEEDS_CLARIFICATION, "Needs Clarification"),
        (PARTICIPANT_COMPLETED, "Completed"),
        (PARTICIPANT_CLOSED, "Closed"),
    ]

    ticket_number = models.CharField(max_length=20, unique=True, editable=False)
    external_reference = models.CharField(max_length=100, blank=True, db_index=True)
    title = models.CharField(max_length=255)
    description = models.TextField()
    ticket_type = models.ForeignKey(ClientTicketType, null=True, blank=True, on_delete=models.SET_NULL)
    ticket_type_other = models.CharField(max_length=255, blank=True)

    requester = models.ForeignKey(
        ClientContact,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    requester_name = models.CharField(max_length=255)
    requester_email = models.EmailField()
    requester_number = models.CharField(max_length=30)

    assigned_to = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="client_tickets_assigned",
    )
    project_manager = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="client_tickets_managed",
    )
    created_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="client_tickets_created",
    )
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL)

    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default=USER_TYPE_INTERNAL)
    source_system = models.CharField(max_length=30, choices=SOURCE_SYSTEM_CHOICES, default=SOURCE_MANUAL)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, blank=True, default="")
    inditech_status = models.CharField(
        max_length=32,
        choices=PARTICIPANT_STATUS_CHOICES,
        blank=True,
        default="",
    )
    client_status = models.CharField(
        max_length=32,
        choices=PARTICIPANT_STATUS_CHOICES,
        blank=True,
        default="",
    )

    last_inditech_action_at = models.DateTimeField(null=True, blank=True)
    last_client_action_at = models.DateTimeField(null=True, blank=True)
    last_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    inditech_completed_at = models.DateTimeField(null=True, blank=True)
    client_completed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    auto_closed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_system", "external_reference"],
                condition=~Q(external_reference=""),
                name="unique_client_ticket_source_external_reference",
            )
        ]

    def save(self, *args, **kwargs):
        now = timezone.now()
        self.external_reference = (self.external_reference or "").strip()
        self.requester_email = normalize_email(self.requester_email)
        self.requester_number = normalize_phone_number(self.requester_number)
        self.requester_name = (self.requester_name or "").strip()
        self.ticket_type_other = (self.ticket_type_other or "").strip()

        if self.ticket_type and self.ticket_type.department and not self.department:
            self.department = self.ticket_type.department

        if not self.ticket_number:
            self.ticket_number = self.generate_ticket_number()

        if self.inditech_status in {self.PARTICIPANT_COMPLETED, self.PARTICIPANT_CLOSED} and not self.inditech_completed_at:
            self.inditech_completed_at = now
        if self.client_status in {self.PARTICIPANT_COMPLETED, self.PARTICIPANT_CLOSED} and not self.client_completed_at:
            self.client_completed_at = now
        if self.status in {self.STATUS_CLOSED, self.STATUS_AUTO_CLOSED} and not self.closed_at:
            self.closed_at = now

        super().save(*args, **kwargs)

    def generate_ticket_number(self):
        while True:
            candidate = f"CLT-{uuid.uuid4().hex[:8].upper()}"
            if not ClientTicket.objects.filter(ticket_number=candidate).exists():
                return candidate

    @property
    def ticket_type_label(self):
        if self.ticket_type_id:
            return self.ticket_type.name
        return self.ticket_type_other or "-"

    @property
    def is_closed(self):
        return self.status in {self.STATUS_CLOSED, self.STATUS_AUTO_CLOSED, self.STATUS_CANCELLED}

    def get_absolute_url(self):
        return reverse("client_tickets:ticket_detail", args=[self.ticket_number])

    def __str__(self):
        return f"{self.ticket_number} - {self.title}"


class ClientTicketUpdate(models.Model):
    ACTOR_INDITECH = "inditech"
    ACTOR_CLIENT = "client"
    ACTOR_SYSTEM = "system"
    ACTOR_CHOICES = [
        (ACTOR_INDITECH, "Inditech"),
        (ACTOR_CLIENT, "Client"),
        (ACTOR_SYSTEM, "System"),
    ]

    ticket = models.ForeignKey(ClientTicket, on_delete=models.CASCADE, related_name="updates")
    actor_type = models.CharField(max_length=20, choices=ACTOR_CHOICES)
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="client_ticket_updates",
    )
    client = models.ForeignKey(
        ClientContact,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ticket_updates",
    )
    message = models.TextField(blank=True)
    status = models.CharField(max_length=32, choices=ClientTicket.STATUS_CHOICES, blank=True, default="")
    inditech_status = models.CharField(
        max_length=32,
        choices=ClientTicket.PARTICIPANT_STATUS_CHOICES,
        blank=True,
        default="",
    )
    client_status = models.CharField(
        max_length=32,
        choices=ClientTicket.PARTICIPANT_STATUS_CHOICES,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ticket.ticket_number} update by {self.get_actor_type_display()}"


class ClientTicketAttachment(models.Model):
    UPLOADER_CLIENT = "client"
    UPLOADER_PM = "pm"
    UPLOADER_INDITECH = "inditech"
    UPLOADER_CHOICES = [
        (UPLOADER_CLIENT, "Client"),
        (UPLOADER_PM, "Project Manager"),
        (UPLOADER_INDITECH, "Inditech"),
    ]

    ticket = models.ForeignKey(ClientTicket, on_delete=models.CASCADE, related_name="attachments")
    update = models.ForeignKey(
        ClientTicketUpdate,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attachments",
    )
    file = models.FileField(upload_to=client_ticket_upload_to)
    uploaded_by_role = models.CharField(max_length=20, choices=UPLOADER_CHOICES)
    uploaded_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="client_ticket_attachments",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    @property
    def filename(self):
        return os.path.basename(self.file.name)

    def __str__(self):
        return f"{self.ticket.ticket_number} - {self.filename}"
