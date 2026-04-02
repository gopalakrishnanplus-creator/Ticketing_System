from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from client_tickets.models import ClientTicket, ClientTicketType
from task_app.models import Department, Task, TaskAttachment, UserProfile


@override_settings(CLIENT_TICKETS_BASE_URL="http://127.0.0.1:5467")
class UserProfileClientTicketAccessTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Testing")
        self.user = User.objects.create_user(
            username="profileuser",
            email="profile@example.com",
            password="password123",
            first_name="Profile",
            last_name="User",
        )
        UserProfile.objects.create(
            user=self.user,
            category="Non-Management",
            department=self.department,
        )
        self.ticket_type, _ = ClientTicketType.objects.get_or_create(
            name="Testing",
            defaults={"department": self.department},
        )
        if self.ticket_type.department_id != self.department.id:
            self.ticket_type.department = self.department
            self.ticket_type.save(update_fields=["department"])

        ClientTicket.objects.create(
            title="Visible from profile",
            description="This ticket should appear in the profile summary.",
            requester_name="Client",
            requester_email="client@example.com",
            requester_number="+919999999999",
            assigned_to=self.user,
            project_manager=self.user,
            created_by=self.user,
            department=self.department,
            ticket_type=self.ticket_type,
            status=ClientTicket.STATUS_OPEN,
        )

    def test_user_profile_shows_client_ticket_access(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("user_profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Client Tickets Overview")
        self.assertContains(response, "External Assigned to Me")
        self.assertContains(response, "All Client Tickets")
        self.assertEqual(response.context["client_ticket_summary"]["assigned_to_me"], 1)


@override_settings(CLIENT_TICKETS_BASE_URL="http://127.0.0.1:5467")
class TicketModeNavigationTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Technology")
        self.user = User.objects.create_user(
            username="navuser",
            email="nav@example.com",
            password="password123",
            first_name="Nav",
            last_name="User",
        )
        UserProfile.objects.create(
            user=self.user,
            category="Non-Management",
            department=self.department,
        )
        self.client.force_login(self.user)

        self.internal_task = Task.objects.create(
            department=self.department,
            assigned_by=self.user,
            assigned_to=self.user,
            deadline=date.today() + timedelta(days=2),
            ticket_type="Testing",
            priority="high",
            status="Not Started",
            subject="Internal launch task",
            request_details="Internal workflow item",
        )

        self.ticket_type, _ = ClientTicketType.objects.get_or_create(
            name="Campaign Management",
            defaults={"department": self.department},
        )
        if self.ticket_type.department_id != self.department.id:
            self.ticket_type.department = self.department
            self.ticket_type.save(update_fields=["department"])

        self.external_ticket = ClientTicket.objects.create(
            title="External reporting ticket",
            description="External workflow item",
            requester_name="Client Person",
            requester_email="clientmode@example.com",
            requester_number="+919999999998",
            assigned_to=self.user,
            project_manager=self.user,
            created_by=self.user,
            department=self.department,
            ticket_type=self.ticket_type,
            status=ClientTicket.STATUS_OPEN,
        )

    def test_dashboard_redirects_to_assigned_to_me(self):
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, reverse("assigned_to_me"))

    def test_toggle_persists_external_mode_across_pages(self):
        initial_response = self.client.get(reverse("assigned_to_me"))
        self.assertContains(initial_response, "Internal launch task")
        self.assertNotContains(initial_response, "External reporting ticket")

        toggle_response = self.client.get(
            reverse("set_ticket_mode", args=["external"]),
            {"next": reverse("assigned_to_me")},
            follow=True,
        )

        self.assertEqual(self.client.session["ticket_ui_mode"], "external")
        self.assertContains(toggle_response, "External reporting ticket")
        self.assertNotContains(toggle_response, "Internal launch task")

        next_page = self.client.get(reverse("assigned_by_me"))
        self.assertContains(next_page, "External reporting ticket")
        self.assertNotContains(next_page, "Internal launch task")


@override_settings(CLIENT_TICKETS_BASE_URL="http://127.0.0.1:5467")
class ManagerTicketVisibilityTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Operations")
        self.manager = User.objects.create_user(
            username="deptmanager",
            email="manager@example.com",
            password="password123",
            first_name="Dept",
            last_name="Manager",
        )
        self.staff = User.objects.create_user(
            username="staffmember",
            email="staff@example.com",
            password="password123",
            first_name="Staff",
            last_name="Member",
        )
        UserProfile.objects.create(
            user=self.manager,
            category="Departmental Manager",
            department=self.department,
        )
        UserProfile.objects.create(
            user=self.staff,
            category="Non-Management",
            department=self.department,
        )

        Task.objects.create(
            department=self.department,
            assigned_by=self.staff,
            assigned_to=self.staff,
            deadline=date.today() + timedelta(days=3),
            ticket_type="Testing",
            priority="medium",
            status="In Progress",
            subject="Department scoped task",
            request_details="Should be visible to the department manager.",
        )

    def test_department_manager_can_see_department_tasks_on_assigned_page(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("assigned_to_me"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Department scoped task")


@override_settings(
    CLIENT_TICKETS_BASE_URL="http://127.0.0.1:5467",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class InternalTaskAttachmentTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Technology")
        self.user = User.objects.create_user(
            username="attachmentuser",
            email="attachment@example.com",
            password="password123",
            first_name="Attachment",
            last_name="User",
        )
        UserProfile.objects.create(
            user=self.user,
            category="Non-Management",
            department=self.department,
        )
        self.client.force_login(self.user)

    def test_internal_task_can_be_created_with_multiple_attachments(self):
        attachment_one = SimpleUploadedFile("brief.txt", b"brief", content_type="text/plain")
        attachment_two = SimpleUploadedFile("design.txt", b"design", content_type="text/plain")

        response = self.client.post(
            reverse("create_task"),
            data={
                "assigned_to": self.user.id,
                "deadline": (date.today() + timedelta(days=2)).isoformat(),
                "ticket_type": "Testing",
                "priority": "high",
                "department": self.department.id,
                "subject": "Attachment test task",
                "request_details": "Testing multi-attachment upload.",
                "status": "Not Started",
                "viewers_ui": [self.user.id],
                "attachments": [attachment_one, attachment_two],
            },
        )

        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(subject="Attachment test task")
        self.assertEqual(task.attachments.count(), 2)
        self.assertEqual(task.viewers, [self.user.email])
        email_html = "\n".join(message.alternatives[0][0] for message in mail.outbox if message.alternatives)
        self.assertIn("Attachment test task", email_html)
        self.assertIn("brief.txt", email_html)
        self.assertIn("design.txt", email_html)
        self.assertIn("Download Attachment", email_html)

    def test_internal_task_attachment_size_limit_is_enforced(self):
        oversized_attachment = SimpleUploadedFile(
            "oversized.txt",
            b"x" * ((5 * 1024 * 1024) + 1),
            content_type="text/plain",
        )

        response = self.client.post(
            reverse("create_task"),
            data={
                "assigned_to": self.user.id,
                "deadline": (date.today() + timedelta(days=2)).isoformat(),
                "ticket_type": "Testing",
                "priority": "high",
                "department": self.department.id,
                "subject": "Oversized attachment task",
                "request_details": "This should fail.",
                "status": "Not Started",
                "attachments": [oversized_attachment],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "file size exceeds 5 MB", status_code=400)
        self.assertFalse(Task.objects.filter(subject="Oversized attachment task").exists())
        self.assertEqual(TaskAttachment.objects.count(), 0)

    def test_task_detail_page_shows_mail_style_attachment_downloads(self):
        task = Task.objects.create(
            department=self.department,
            assigned_by=self.user,
            assigned_to=self.user,
            deadline=date.today() + timedelta(days=2),
            ticket_type="Testing",
            priority="medium",
            status="In Progress",
            subject="Mail style detail task",
            request_details="Need a polished detail page.",
            comments_by_assignee="Comment for detail page.",
        )
        TaskAttachment.objects.create(
            task=task,
            uploaded_by=self.user,
            file=SimpleUploadedFile("handoff.txt", b"handoff", content_type="text/plain"),
        )

        response = self.client.get(reverse("task_detail", args=[task.task_id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Request Body")
        self.assertContains(response, "handoff.txt")
        self.assertContains(response, "Download")
