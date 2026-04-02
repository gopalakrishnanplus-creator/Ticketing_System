from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from client_tickets.models import ClientTicket, ClientTicketType
from task_app.models import Department, UserProfile


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
        self.assertContains(response, "Client Tickets Dashboard")
        self.assertContains(response, "All Client Tickets")
        self.assertEqual(response.context["client_ticket_summary"]["assigned_to_me"], 1)
