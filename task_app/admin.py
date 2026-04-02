# task_app/admin.py

from django.contrib import admin
from .models import Task, UserProfile, Department, TaskChat
from .models import ActivityLog

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('task_id', 'assigned_by', 'assigned_to', 'department', 'deadline')
    search_fields = ('task_id', 'assigned_by__username', 'assigned_to__username')
@admin.register(TaskChat)
class TaskChatAdmin(admin.ModelAdmin):
    list_display = ('task', 'sender', 'timestamp')
    list_filter = ('task', 'sender')

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'category', 'department', 'reports_to')
    search_fields = ('user__username', 'category')

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'task', 'timestamp', 'description')  # Display these columns
    list_filter = ('action', 'timestamp')  # Add filters for easier navigation
    search_fields = ('user__username', 'task__task_id', 'description')  # Enable searching by user, task ID, and description
    ordering = ('-timestamp',)  # Order by most recent activity
