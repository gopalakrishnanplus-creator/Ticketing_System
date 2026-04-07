from django.urls import path

from . import views


app_name = "client_tickets"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/create/", views.create_ticket, name="create_ticket"),
    path("tickets/<str:ticket_number>/", views.ticket_detail, name="ticket_detail"),
    path("api/tickets/", views.api_tickets, name="api_create_ticket"),
    path("api/tickets/by-external-reference/", views.api_ticket_by_external_reference, name="api_ticket_by_external_reference"),
    path("api/tickets/<str:ticket_number>/", views.api_ticket_detail, name="api_ticket_detail"),
    path("api/tickets/<str:ticket_number>/inditech-update/", views.api_inditech_update_ticket, name="api_inditech_update_ticket"),
    path("api/tickets/<str:ticket_number>/client-update/", views.api_client_update_ticket, name="api_client_update_ticket"),
    path("api/lookups/departments/", views.api_lookup_departments, name="api_lookup_departments"),
    path("api/lookups/ticket-types/", views.api_lookup_ticket_types, name="api_lookup_ticket_types"),
    path("api/lookups/users/", views.api_lookup_users, name="api_lookup_users"),
    path("api/lookups/project-managers/", views.api_lookup_project_managers, name="api_lookup_project_managers"),
]
