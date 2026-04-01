from django.contrib import admin

from .models import ClientContact, ClientTicket, ClientTicketAttachment, ClientTicketType, ClientTicketUpdate


@admin.register(ClientContact)
class ClientContactAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "phone_number", "updated_at")
    search_fields = ("name", "email", "phone_number")


@admin.register(ClientTicketType)
class ClientTicketTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "is_active")
    list_filter = ("is_active", "department")
    search_fields = ("name",)


class ClientTicketAttachmentInline(admin.TabularInline):
    model = ClientTicketAttachment
    extra = 0
    readonly_fields = ("uploaded_at",)


class ClientTicketUpdateInline(admin.TabularInline):
    model = ClientTicketUpdate
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(ClientTicket)
class ClientTicketAdmin(admin.ModelAdmin):
    list_display = (
        "ticket_number",
        "title",
        "requester_name",
        "assigned_to",
        "project_manager",
        "priority",
        "status",
        "updated_at",
    )
    list_filter = ("priority", "status", "source_system", "department")
    search_fields = ("ticket_number", "title", "requester_name", "requester_email")
    inlines = [ClientTicketUpdateInline, ClientTicketAttachmentInline]


@admin.register(ClientTicketUpdate)
class ClientTicketUpdateAdmin(admin.ModelAdmin):
    list_display = ("ticket", "actor_type", "status", "inditech_status", "client_status", "created_at")
    list_filter = ("actor_type", "status", "inditech_status", "client_status")
    search_fields = ("ticket__ticket_number", "message")


@admin.register(ClientTicketAttachment)
class ClientTicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "filename", "uploaded_by_role", "uploaded_at")
    list_filter = ("uploaded_by_role",)
    search_fields = ("ticket__ticket_number", "file")
