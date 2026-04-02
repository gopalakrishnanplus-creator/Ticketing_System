from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from task_app.models import Department

from .models import ClientContact, ClientTicket, ClientTicketAttachment, ClientTicketType
from .services import auto_close_stale_tickets, notify_ticket_created, send_unchecked_ticket_reminders


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    CLIENT_TICKETS_BASE_URL="http://127.0.0.1:5467",
)
class ClientTicketTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Testing")
        self.assigned_to = User.objects.create_user(
            username="assignee",
            email="assignee@example.com",
            password="password123",
            first_name="Assigned",
            last_name="User",
        )
        self.project_manager = User.objects.create_user(
            username="pm",
            email="pm@example.com",
            password="password123",
            first_name="Project",
            last_name="Manager",
        )
        self.ticket_type, _ = ClientTicketType.objects.get_or_create(
            name="PM Dashboard",
            defaults={"department": self.department},
        )
        if self.ticket_type.department_id != self.department.id:
            self.ticket_type.department = self.department
            self.ticket_type.save(update_fields=["department"])

    def test_api_can_create_client_ticket(self):
        url = reverse("client_tickets:api_create_ticket")
        response = self.client.post(
            url,
            data={
                "title": "Campaign reporting issue",
                "description": "Metrics are delayed by 2 hours.",
                "ticket_type_id": self.ticket_type.id,
                "requester_name": "Asha Shah",
                "requester_email": "asha@example.com",
                "requester_number": "+91 98765 43210",
                "assigned_to_email": self.assigned_to.email,
                "project_manager_email": self.project_manager.email,
                "department_id": self.department.id,
                "source_system": ClientTicket.SOURCE_PM_DASHBOARD,
                "priority": ClientTicket.PRIORITY_HIGH,
            },
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertTrue(payload["success"])
        ticket = ClientTicket.objects.get(ticket_number=payload["ticket"]["ticket_number"])
        self.assertEqual(ticket.requester_email, "asha@example.com")
        self.assertEqual(ticket.requester_number, "+919876543210")
        self.assertEqual(ticket.status, ClientTicket.STATUS_OPEN)

    def test_unchecked_ticket_reminder_sends_mail(self):
        contact = ClientContact.objects.create(
            name="Ravi Mehta",
            email="ravi@example.com",
            phone_number="9999988888",
        )
        ticket = ClientTicket.objects.create(
            title="Creative asset correction",
            description="Need one more revision on the static.",
            requester=contact,
            requester_name=contact.name,
            requester_email=contact.email,
            requester_number=contact.phone_number,
            assigned_to=self.assigned_to,
            project_manager=self.project_manager,
            department=self.department,
            ticket_type=self.ticket_type,
            priority=ClientTicket.PRIORITY_MEDIUM,
            status=ClientTicket.STATUS_OPEN,
        )
        ClientTicket.objects.filter(id=ticket.id).update(created_at=timezone.now() - timedelta(days=2))

        sent_count = send_unchecked_ticket_reminders()

        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(ticket.ticket_number, mail.outbox[0].subject)

    def test_auto_close_after_inditech_completion_without_client_close(self):
        contact = ClientContact.objects.create(
            name="Nina Client",
            email="nina@example.com",
            phone_number="8888877777",
        )
        ticket = ClientTicket.objects.create(
            title="API sync closure",
            description="Waiting for client confirmation.",
            requester=contact,
            requester_name=contact.name,
            requester_email=contact.email,
            requester_number=contact.phone_number,
            assigned_to=self.assigned_to,
            project_manager=self.project_manager,
            department=self.department,
            ticket_type=self.ticket_type,
            priority=ClientTicket.PRIORITY_LOW,
            status=ClientTicket.STATUS_RESOLVED,
            inditech_status=ClientTicket.PARTICIPANT_COMPLETED,
        )
        ClientTicket.objects.filter(id=ticket.id).update(inditech_completed_at=timezone.now() - timedelta(days=8))

        closed_count = auto_close_stale_tickets()

        ticket.refresh_from_db()
        self.assertEqual(closed_count, 1)
        self.assertEqual(ticket.status, ClientTicket.STATUS_AUTO_CLOSED)
        self.assertIsNotNone(ticket.auto_closed_at)

    def test_client_ticket_email_and_detail_show_download_actions(self):
        contact = ClientContact.objects.create(
            name="Rutu Client",
            email="rutu@example.com",
            phone_number="7777766666",
        )
        ticket = ClientTicket.objects.create(
            title="Attachment rich client ticket",
            description="Client ticket body for the email summary.",
            requester=contact,
            requester_name=contact.name,
            requester_email=contact.email,
            requester_number=contact.phone_number,
            assigned_to=self.assigned_to,
            project_manager=self.project_manager,
            department=self.department,
            ticket_type=self.ticket_type,
            priority=ClientTicket.PRIORITY_HIGH,
            status=ClientTicket.STATUS_OPEN,
        )
        ClientTicketAttachment.objects.create(
            ticket=ticket,
            uploaded_by=self.project_manager,
            uploaded_by_role=ClientTicketAttachment.UPLOADER_PM,
            file=SimpleUploadedFile("proof.pdf", b"proof", content_type="application/pdf"),
        )

        notify_ticket_created(ticket)

        self.assertEqual(len(mail.outbox), 1)
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn("Attachment rich client ticket", html_body)
        self.assertIn("proof.pdf", html_body)
        self.assertIn("Download Attachment", html_body)

        self.client.force_login(self.assigned_to)
        response = self.client.get(reverse("client_tickets:ticket_detail", args=[ticket.ticket_number]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ticket Body")
        self.assertContains(response, "proof.pdf")
        self.assertContains(response, "Download")
