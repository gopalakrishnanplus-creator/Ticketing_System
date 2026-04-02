from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from client_tickets.models import ClientTicket, ClientTicketType
from task_app.models import Department, Task, UserProfile


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
