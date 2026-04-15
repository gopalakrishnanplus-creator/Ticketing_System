from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Department, Task, UserProfile


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class UpdateTaskStatusEmailTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Executive Managers")
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password123",
            first_name="Owner",
            last_name="User",
        )
        self.assignee = User.objects.create_user(
            username="assignee",
            email="assignee@example.com",
            password="password123",
            first_name="Assignee",
            last_name="User",
        )
        UserProfile.objects.create(
            user=self.owner,
            category="Executive Management",
            department=self.department,
        )
        UserProfile.objects.create(
            user=self.assignee,
            category="Non-Management",
            department=self.department,
        )
        self.task = Task.objects.create(
            department=self.department,
            assigned_by=self.owner,
            assigned_to=self.assignee,
            deadline=date.today() + timedelta(days=2),
            ticket_type="Testing",
            priority="high",
            status="In Progress",
            subject="Video creation and content localisation",
            request_details="Test request body",
        )

    def test_update_task_status_comment_email_renders_with_completion(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("update_task_status", args=[self.task.task_id]),
            {
                "status": "Completed",
                "comments_by_assignee": "Marked as completed after final review.",
                "revised_completion_date": "",
            },
        )

        self.assertRedirects(response, reverse("task_detail", args=[self.task.task_id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "Completed")
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Comment Updated", mail.outbox[0].subject)
        self.assertIn("updated the ticket comments", mail.outbox[0].alternatives[0][0])
