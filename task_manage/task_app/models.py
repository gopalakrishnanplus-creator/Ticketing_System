from django.db import models
from django.contrib.auth.models import User
import random
import string
from datetime import timedelta,datetime,date, timezone
from django.utils import timezone

class Department(models.Model):
    name = models.CharField(max_length=50)
    manager = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_departments')

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    USER_CATEGORIES = [
        ('Executive Management', 'Executive Management'),
        ('Departmental Manager', 'Departmental Manager'),
        ('Non-Management', 'Non-Management'),
        ('Task Management System Manager', 'Task Management System Manager'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    category = models.CharField(max_length=50, choices=USER_CATEGORIES)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    reports_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='reports')

    def __str__(self):
        return self.user.username

class Task(models.Model):
    STATUS_CHOICES = [
        ('Not Started', 'Not Started'),
        ('In Progress', 'In Progress'),
        ('Completed', 'Completed'),
        ('Stalled', 'Stalled'),
        ('On-Hold', 'On-Hold'),
        ('Cancelled', 'Cancelled'),
        ('Overdue', 'Overdue'),  # Added Overdue status
    ]

    PRIORITY_LEVELS = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent')
    ]

    FUNCTIONAL_CATEGORIES = [
        ('Bug Fixing - Live', 'Bug Fixing - Live'),
        ('Bug Fixing - Staging', 'Bug Fixing - Staging'),
        ('Hardware', 'Hardware'),
        ('Issues', 'Issues'),
        ('New Engineering Requirement', 'New Engineering Requirement'),
        ('Others', 'Others'),
        ('Publishing', 'Publishing'),
        ('Research', 'Research'),
        ('Sales', 'Sales'),
        ('Service', 'Service'),
        ('Testing', 'Testing'),
    ]

    IS_RECURRING_CHOICES = [
        (True, 'Yes'),
        (False, 'No'),
    ]

    RECURRENCE_TYPE_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
    ]

    # Fields for the Task model
    task_id = models.CharField(max_length=15, unique=True, editable=False)
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True, blank=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='tasks_assigned')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='tasks_received')
    assigned_date = models.DateTimeField(default=timezone.now)
    deadline = models.DateField()
    ticket_type = models.CharField(max_length=100, choices=FUNCTIONAL_CATEGORIES)
    priority = models.CharField(max_length=10, choices=PRIORITY_LEVELS)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Not Started')
    subject = models.CharField(max_length=255)
    request_details = models.TextField(blank=True, null=True)
    attach_file = models.FileField(upload_to='attachments/', blank=True, null=True)
    revised_completion_date = models.DateField(null=True, blank=True)
    comments_by_assignee = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    is_recurring = models.BooleanField(default=False)
    recurrence_type = models.CharField(max_length=10, choices=RECURRENCE_TYPE_CHOICES, null=True, blank=True)
    recurrence_count = models.IntegerField(default=1)
    recurrence_duration = models.IntegerField(default=1)
    # NEW: list of viewer emails (can include external emails too)
    viewers = models.JSONField(default=list, blank=True)
    is_recurred_task = models.BooleanField(default=False)

    # New field for attachment uploaded by assignee
    attachment_by_assignee = models.FileField(upload_to='task_assignee_attachments/', blank=True, null=True)

    def save(self, *args, **kwargs):
        # Automatically set status to 'Overdue' if the deadline has passed
        if self.deadline < date.today() and self.status != 'Completed' and self.status != 'Cancelled':
            if not self.revised_completion_date or self.revised_completion_date < date.today():
                self.status = 'Overdue'
            else:
                self.status = 'In Progress'

        if not self.task_id:
            self.task_id = self.generate_task_id()

        if self.is_recurring:
            self.create_recurring_tasks()

        super(Task, self).save(*args, **kwargs)
    @property
    def viewer_users(self):
        """Convenience: Users whose email appears in viewers (for UI)."""
        from django.contrib.auth.models import User
        return User.objects.filter(email__in=self.viewers)

    def generate_task_id(self):
        prefix = ''
        if self.department:
            prefix = self.department.name[:3].upper()
        random_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return f"{prefix}-{random_code}"

    def create_recurring_tasks(self):
        """
        Create new recurring tasks based on recurrence type, count, and duration.
        """
        self.assigned_date = date.today()
        for i in range(1, self.recurrence_count + 1):
            if self.recurrence_type == 'daily':
                new_assigned_date = self.assigned_date + timedelta(days=i * self.recurrence_duration)
                new_deadline = self.deadline + timedelta(days=i * self.recurrence_duration)
            elif self.recurrence_type == 'weekly':
                new_assigned_date = self.assigned_date + timedelta(weeks=i * self.recurrence_duration)
                new_deadline = self.deadline + timedelta(weeks=i * self.recurrence_duration)
            else:
                continue

            new_task = Task(
                assigned_by=self.assigned_by,
                assigned_to=self.assigned_to,
                department=self.department,
                ticket_type=self.ticket_type,
                priority=self.priority,
                status=self.status,
                subject=self.subject,
                request_details=self.request_details,
                is_recurring=False,  # Newly created tasks are not recurring
                is_recurred_task=True,  # Mark as recurred task
                recurrence_type=None,
                recurrence_count=self.recurrence_count,
                recurrence_duration=self.recurrence_duration,
                assigned_date=new_assigned_date,
                deadline=new_deadline,
                attach_file=self.attach_file,
                notes=self.notes
            )
            new_task.save()


class TaskChat(models.Model):
    """
    Model to store chat messages for a specific task
    """
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='chat_messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Message by {self.sender.username} on {self.task.task_id} at {self.timestamp}"

    
class ActivityLog(models.Model):
    ACTION_CHOICES = [
        ('created', 'Created'),
        ('status_updated', 'Status Updated'),
        ('priority_changed', 'Priority Changed'),
        ('deadline_revised', 'Deadline Revised'),
        ('comment_added', 'Comment Added'),
        ('assigned', 'Assigned'),
        ('reassigned','Reassigned')
    ]

    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} {self.action} task {self.task.task_id} on {self.timestamp}"
