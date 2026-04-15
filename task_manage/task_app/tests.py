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


class TaskRenderingSafetyTests(TestCase):
    def setUp(self):
        self.department = Department.objects.create(name="Technology")
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
            category="Non-Management",
            department=self.department,
        )
        UserProfile.objects.create(
            user=self.assignee,
            category="Non-Management",
            department=self.department,
        )

    def test_assigned_by_me_renders_when_task_has_no_assignee(self):
        task = Task.objects.create(
            department=self.department,
            assigned_by=self.owner,
            assigned_to=None,
            assigned_date=date.today(),
            deadline=date.today() + timedelta(days=1),
            ticket_type="Testing",
            priority="medium",
            status="Not Started",
            subject="Unassigned task",
            request_details="Should render safely.",
        )
        self.client.force_login(self.owner)

        response = self.client.get(f"{reverse('assigned_by_me')}?page=2")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, task.task_id)
        self.assertContains(response, "Unassigned")

    def test_assigned_to_me_renders_when_creator_is_missing(self):
        task = Task.objects.create(
            department=self.department,
            assigned_by=None,
            assigned_to=self.assignee,
            assigned_date=date.today(),
            deadline=date.today() + timedelta(days=1),
            ticket_type="Testing",
            priority="medium",
            status="Not Started",
            subject="Creator removed",
            request_details="Should render safely.",
        )
        self.client.force_login(self.assignee)

        response = self.client.get(reverse("assigned_to_me"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, task.task_id)
        self.assertContains(response, "Unknown creator")

    def test_task_detail_renders_when_assignment_links_are_missing(self):
        task = Task.objects.create(
            department=self.department,
            assigned_by=self.owner,
            assigned_to=None,
            assigned_date=date.today(),
            deadline=date.today() + timedelta(days=1),
            ticket_type="Testing",
            priority="medium",
            status="In Progress",
            subject="Detail without assignee",
            request_details="Should render safely.",
        )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("task_detail", args=[task.task_id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unassigned")
