from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from task_app.models import Department, UserProfile

from .models import ClientContact, ClientTicket, ClientTicketAttachment, ClientTicketType
from .services import auto_close_stale_tickets, create_ticket_update, notify_ticket_created, send_unchecked_ticket_reminders
from .utils import build_absolute_link


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
        UserProfile.objects.create(
            user=self.assigned_to,
            category="Non-Management",
            department=self.department,
        )
        UserProfile.objects.create(
            user=self.project_manager,
            category="Departmental Manager",
            department=self.department,
        )
        self.department.manager = self.project_manager
        self.department.save(update_fields=["manager"])
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

    def test_api_create_ticket_supports_external_reference_and_machine_fields(self):
        response = self.client.post(
            reverse("client_tickets:api_create_ticket"),
            data={
                "title": "Campaign mirrored ticket",
                "description": "Created from campaign system.",
                "ticket_type_id": self.ticket_type.id,
                "requester_name": "Mirror User",
                "requester_email": "mirror@example.com",
                "requester_number": "+91 90000 11111",
                "assigned_to_email": self.assigned_to.email,
                "project_manager_email": self.project_manager.email,
                "department_id": self.department.id,
                "source_system": ClientTicket.SOURCE_CAMPAIGN,
                "priority": ClientTicket.PRIORITY_URGENT,
                "status": ClientTicket.STATUS_OPEN,
                "external_reference": "TKT-632AB97A",
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()["ticket"]
        self.assertEqual(payload["external_reference"], "TKT-632AB97A")
        self.assertEqual(payload["source_system_code"], ClientTicket.SOURCE_CAMPAIGN)
        self.assertEqual(payload["priority_code"], ClientTicket.PRIORITY_URGENT)
        self.assertEqual(payload["status_code"], ClientTicket.STATUS_OPEN)
        self.assertEqual(payload["assigned_to_email"], self.assigned_to.email)
        self.assertEqual(payload["project_manager_email"], self.project_manager.email)

    def test_api_create_ticket_ignores_unknown_project_manager_email(self):
        response = self.client.post(
            reverse("client_tickets:api_create_ticket"),
            data={
                "title": "Campaign ticket without valid pm",
                "description": "Should still create even if PM email does not match a user.",
                "ticket_type_id": self.ticket_type.id,
                "requester_name": "Campaign Sync",
                "requester_email": "sync@example.com",
                "requester_number": "+91 99888 77777",
                "assigned_to_email": self.assigned_to.email,
                "project_manager_email": "campaignpm@inditech.co.in",
                "department_id": self.department.id,
                "source_system": ClientTicket.SOURCE_CAMPAIGN,
                "priority": ClientTicket.PRIORITY_MEDIUM,
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()["ticket"]
        ticket = ClientTicket.objects.get(ticket_number=payload["ticket_number"])
        self.assertIsNone(ticket.project_manager)
        self.assertEqual(payload["project_manager_email"], "")

    def test_ticket_pages_render_when_project_manager_is_missing(self):
        contact = ClientContact.objects.create(
            name="UI User",
            email="ui@example.com",
            phone_number="9999922222",
        )
        ticket = ClientTicket.objects.create(
            title="UI safe without PM",
            description="The template should not crash without a project manager.",
            requester=contact,
            requester_name=contact.name,
            requester_email=contact.email,
            requester_number=contact.phone_number,
            assigned_to=self.assigned_to,
            project_manager=None,
            department=self.department,
            ticket_type=self.ticket_type,
            source_system=ClientTicket.SOURCE_CAMPAIGN,
            priority=ClientTicket.PRIORITY_MEDIUM,
            status=ClientTicket.STATUS_OPEN,
        )
        self.client.force_login(self.assigned_to)

        list_response = self.client.get(reverse("client_tickets:ticket_list"))
        detail_response = self.client.get(reverse("client_tickets:ticket_detail", args=[ticket.ticket_number]))

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "No project manager")
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "No project manager")

    def test_api_ticket_detail_returns_machine_codes_and_updates(self):
        contact = ClientContact.objects.create(
            name="Detail User",
            email="detail@example.com",
            phone_number="9999911111",
        )
        ticket = ClientTicket.objects.create(
            external_reference="TKT-DETAIL-1",
            title="Detail contract ticket",
            description="Need machine readable response.",
            requester=contact,
            requester_name=contact.name,
            requester_email=contact.email,
            requester_number=contact.phone_number,
            assigned_to=self.assigned_to,
            project_manager=self.project_manager,
            department=self.department,
            ticket_type=self.ticket_type,
            source_system=ClientTicket.SOURCE_CAMPAIGN,
            priority=ClientTicket.PRIORITY_HIGH,
            status=ClientTicket.STATUS_OPEN,
        )
        create_ticket_update(
            ticket,
            actor_type="system",
            message="Ticket created.",
            status=ClientTicket.STATUS_OPEN,
        )
        create_ticket_update(
            ticket,
            actor_type="inditech",
            message="Working on it",
            status=ClientTicket.STATUS_IN_PROGRESS,
            inditech_status=ClientTicket.PARTICIPANT_IN_PROGRESS,
            user=self.assigned_to,
        )

        response = self.client.get(reverse("client_tickets:api_ticket_detail", args=[ticket.ticket_number]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()["ticket"]
        self.assertEqual(payload["external_reference"], "TKT-DETAIL-1")
        self.assertEqual(payload["ticket_type_id"], self.ticket_type.id)
        self.assertEqual(payload["department_id"], self.department.id)
        self.assertEqual(payload["assigned_to_id"], self.assigned_to.id)
        self.assertEqual(payload["project_manager_id"], self.project_manager.id)
        self.assertEqual(payload["source_system_code"], ClientTicket.SOURCE_CAMPAIGN)
        self.assertEqual(payload["status_code"], ClientTicket.STATUS_IN_PROGRESS)
        self.assertEqual(payload["inditech_status_code"], "")
        self.assertEqual(payload["updates"][0]["status_code"], ClientTicket.STATUS_OPEN)
        self.assertEqual(payload["updates"][1]["status_code"], ClientTicket.STATUS_IN_PROGRESS)
        self.assertEqual(payload["updates"][1]["inditech_status_code"], "")

    def test_lookup_and_sync_apis_return_expected_payloads(self):
        contact = ClientContact.objects.create(
            name="Sync User",
            email="sync@example.com",
            phone_number="8888811111",
        )
        old_ticket = ClientTicket.objects.create(
            external_reference="TKT-OLD-1",
            title="Old ticket",
            description="Old",
            requester=contact,
            requester_name=contact.name,
            requester_email=contact.email,
            requester_number=contact.phone_number,
            assigned_to=self.assigned_to,
            project_manager=self.project_manager,
            department=self.department,
            ticket_type=self.ticket_type,
            source_system=ClientTicket.SOURCE_CAMPAIGN,
            priority=ClientTicket.PRIORITY_LOW,
            status=ClientTicket.STATUS_OPEN,
        )
        fresh_ticket = ClientTicket.objects.create(
            external_reference="TKT-FRESH-1",
            title="Fresh ticket",
            description="Fresh",
            requester=contact,
            requester_name=contact.name,
            requester_email=contact.email,
            requester_number=contact.phone_number,
            assigned_to=self.assigned_to,
            project_manager=self.project_manager,
            department=self.department,
            ticket_type=self.ticket_type,
            source_system=ClientTicket.SOURCE_CAMPAIGN,
            priority=ClientTicket.PRIORITY_URGENT,
            status=ClientTicket.STATUS_IN_PROGRESS,
        )
        ClientTicket.objects.filter(id=old_ticket.id).update(updated_at=timezone.now() - timedelta(days=2))

        departments_response = self.client.get(reverse("client_tickets:api_lookup_departments"))
        ticket_types_response = self.client.get(reverse("client_tickets:api_lookup_ticket_types"))
        users_response = self.client.get(reverse("client_tickets:api_lookup_users"), {"department_id": self.department.id})
        managers_response = self.client.get(reverse("client_tickets:api_lookup_project_managers"))
        sync_response = self.client.get(
            reverse("client_tickets:api_create_ticket"),
            {
                "source_system": ClientTicket.SOURCE_CAMPAIGN,
                "updated_after": (timezone.now() - timedelta(hours=1)).isoformat(),
                "page": 1,
                "page_size": 50,
            },
        )
        external_response = self.client.get(
            reverse("client_tickets:api_ticket_by_external_reference"),
            {"external_reference": fresh_ticket.external_reference, "source_system": ClientTicket.SOURCE_CAMPAIGN},
        )

        self.assertEqual(departments_response.status_code, 200)
        self.assertEqual(ticket_types_response.status_code, 200)
        self.assertEqual(users_response.status_code, 200)
        self.assertEqual(managers_response.status_code, 200)
        self.assertEqual(sync_response.status_code, 200)
        self.assertEqual(external_response.status_code, 200)

        self.assertIn(
            self.department.id,
            [row["id"] for row in departments_response.json()["departments"]],
        )
        self.assertIn(
            self.ticket_type.id,
            [row["id"] for row in ticket_types_response.json()["ticket_types"]],
        )
        self.assertTrue(
            any(row["department_id"] == self.department.id for row in users_response.json()["users"])
        )
        self.assertIn(
            self.assigned_to.id,
            [row["id"] for row in managers_response.json()["project_managers"]],
        )
        self.assertEqual(sync_response.json()["count"], 1)
        self.assertEqual(sync_response.json()["results"][0]["external_reference"], fresh_ticket.external_reference)
        self.assertEqual(external_response.json()["ticket"]["ticket_number"], fresh_ticket.ticket_number)

    def test_system_directory_lookup_returns_users_and_departments(self):
        response = self.client.get(
            reverse("client_tickets:api_lookup_system_directory"),
            {"department_id": self.department.id},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertIn(self.department.id, [row["id"] for row in payload["departments"]])
        self.assertTrue(any(row["id"] == self.assigned_to.id for row in payload["users"]))
        department_row = next(row for row in payload["departments"] if row["id"] == self.department.id)
        self.assertEqual(department_row["manager_id"], self.project_manager.id)
        manager_row = next(
            row for row in payload["department_managers"] if row["department_id"] == self.department.id
        )
        self.assertEqual(manager_row["department_name"], self.department.name)
        self.assertEqual(manager_row["manager_id"], self.project_manager.id)
        self.assertEqual(manager_row["manager_email"], self.project_manager.email)

    def test_inditech_update_api_can_reassign_and_store_external_reference(self):
        new_assignee = User.objects.create_user(
            username="newassignee",
            email="newassignee@example.com",
            password="password123",
            first_name="New",
            last_name="Assignee",
        )
        new_pm = User.objects.create_user(
            username="newpm",
            email="newpm@example.com",
            password="password123",
            first_name="New",
            last_name="PM",
        )
        contact = ClientContact.objects.create(
            name="Reassign User",
            email="reassign@example.com",
            phone_number="7777711111",
        )
        ticket = ClientTicket.objects.create(
            title="Reassign ticket",
            description="Needs reassignment.",
            requester=contact,
            requester_name=contact.name,
            requester_email=contact.email,
            requester_number=contact.phone_number,
            assigned_to=self.assigned_to,
            project_manager=self.project_manager,
            department=self.department,
            ticket_type=self.ticket_type,
            source_system=ClientTicket.SOURCE_CAMPAIGN,
            priority=ClientTicket.PRIORITY_LOW,
            status=ClientTicket.STATUS_OPEN,
        )

        response = self.client.post(
            reverse("client_tickets:api_inditech_update_ticket", args=[ticket.ticket_number]),
            data={
                "updated_by_email": self.assigned_to.email,
                "assigned_to_email": new_assignee.email,
                "project_manager_email": new_pm.email,
                "external_reference": "TKT-REASSIGN-1",
                "priority": ClientTicket.PRIORITY_HIGH,
                "status": ClientTicket.STATUS_IN_PROGRESS,
                "inditech_status": ClientTicket.PARTICIPANT_IN_PROGRESS,
                "message": "Reassigned to the correct owner.",
            },
        )

        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to_id, new_assignee.id)
        self.assertEqual(ticket.project_manager_id, new_pm.id)
        self.assertEqual(ticket.external_reference, "TKT-REASSIGN-1")
        self.assertEqual(ticket.status, ClientTicket.STATUS_IN_PROGRESS)
        self.assertEqual(ticket.inditech_status, "")

    def test_external_detail_page_uses_single_status_update_flow(self):
        contact = ClientContact.objects.create(
            name="Simple Flow User",
            email="simple@example.com",
            phone_number="9999977777",
        )
        ticket = ClientTicket.objects.create(
            title="Single status flow",
            description="Should show one status model in the UI.",
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

        self.client.force_login(self.assigned_to)
        response = self.client.get(reverse("client_tickets:ticket_detail", args=[ticket.ticket_number]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ticket Update")
        self.assertContains(response, "Status")
        self.assertNotContains(response, "Inditech Status")
        self.assertNotContains(response, "Client Status")

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


@override_settings(CLIENT_TICKETS_BASE_URL="https://support.inditech.co.in")
class ClientTicketPublicUrlTests(TestCase):
    def test_build_absolute_link_uses_public_support_domain(self):
        self.assertEqual(
            build_absolute_link("/media/client_ticket_attachments/CLT-66D869F4/dummy.pdf"),
            "https://support.inditech.co.in/media/client_ticket_attachments/CLT-66D869F4/dummy.pdf",
        )
