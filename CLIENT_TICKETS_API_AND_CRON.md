# Client Tickets API And Cron Guide

This document explains how to use the `Client Tickets` API and the automation command that sends reminders, summaries, and auto-closes stale tickets.

## Base URLs

- UI base path: `/client-tickets/`
- API base path: `/client-tickets/api/`
- Local example: `http://127.0.0.1:5467`

## Optional API Token

If you set this Django setting:

```python
CLIENT_TICKETS_API_TOKEN = "your-shared-secret"
```

send the same value in the request header:

```http
X-Client-Ticket-Token: your-shared-secret
```

If the setting is blank, the API currently accepts requests without that header.

## Main API Endpoints

### 1. Create ticket

```http
POST /client-tickets/api/tickets/
```

Supported fields:

- `title`
- `description`
- `ticket_type_id` or `ticket_type`
- `ticket_type_other`
- `requester_name`
- `requester_email`
- `requester_number`
- `assigned_to_email` or `assigned_to_id`
- `project_manager_email` or `project_manager_id`
- `user_type`
- `source_system`
- `priority`
- `department_id` or `department`
- `status`
- `attachments`

JSON example:

```bash
curl -X POST "http://127.0.0.1:5467/client-tickets/api/tickets/" \
  -H "Content-Type: application/json" \
  -H "X-Client-Ticket-Token: your-shared-secret" \
  -d '{
    "title": "Campaign dashboard data mismatch",
    "description": "CTR is not matching between PM dashboard and campaign system.",
    "ticket_type": "PM Dashboard",
    "requester_name": "Ritika Shah",
    "requester_email": "ritika@example.com",
    "requester_number": "+91 9876543210",
    "assigned_to_email": "engineer@inditech.co.in",
    "project_manager_email": "pm@inditech.co.in",
    "user_type": "internal",
    "source_system": "pm_dashboard",
    "priority": "high",
    "department": "Testing",
    "status": "open"
  }'
```

Multipart example with attachments:

```bash
curl -X POST "http://127.0.0.1:5467/client-tickets/api/tickets/" \
  -H "X-Client-Ticket-Token: your-shared-secret" \
  -F "title=Creative revision request" \
  -F "description=Need final asset revision before delivery." \
  -F "ticket_type=Campaign Management" \
  -F "requester_name=Megha" \
  -F "requester_email=megha@example.com" \
  -F "requester_number=9876543210" \
  -F "assigned_to_email=engineer@inditech.co.in" \
  -F "project_manager_email=pm@inditech.co.in" \
  -F "department=Testing" \
  -F "priority=medium" \
  -F "attachments=@/absolute/path/mockup.png" \
  -F "attachments=@/absolute/path/brief.pdf"
```

Attachment limits:

- Maximum total attachments per ticket: `5`
- Maximum size per file: `10 MB`
- Allowed types: `jpg`, `jpeg`, `png`, `pdf`, `mp4`, `heic`, `hevc`

### 2. Get ticket details

```http
GET /client-tickets/api/tickets/<ticket_number>/
```

Token-based example:

```bash
curl "http://127.0.0.1:5467/client-tickets/api/tickets/CLT-1234ABCD/" \
  -H "X-Client-Ticket-Token: your-shared-secret"
```

Requester-auth example when token is not used:

```bash
curl "http://127.0.0.1:5467/client-tickets/api/tickets/CLT-1234ABCD/?requester_email=ritika@example.com&requester_number=%2B919876543210"
```

### 3. Update ticket from Inditech side

```http
POST /client-tickets/api/tickets/<ticket_number>/inditech-update/
```

Example:

```bash
curl -X POST "http://127.0.0.1:5467/client-tickets/api/tickets/CLT-1234ABCD/inditech-update/" \
  -H "Content-Type: application/json" \
  -H "X-Client-Ticket-Token: your-shared-secret" \
  -d '{
    "updated_by_email": "engineer@inditech.co.in",
    "status": "in_progress",
    "inditech_status": "in_progress",
    "message": "Issue reproduced and fix is in progress."
  }'
```

This endpoint can also update:

- `title`
- `description`
- `priority`
- `ticket_type`
- `ticket_type_other`
- `department`
- `attachments`

### 4. Update ticket from client side

```http
POST /client-tickets/api/tickets/<ticket_number>/client-update/
```

Example:

```bash
curl -X POST "http://127.0.0.1:5467/client-tickets/api/tickets/CLT-1234ABCD/client-update/" \
  -H "Content-Type: application/json" \
  -d '{
    "requester_email": "ritika@example.com",
    "requester_number": "+919876543210",
    "client_status": "completed",
    "message": "Confirmed from client side. You can close this ticket."
  }'
```

## Email Behavior

The system sends emails for:

- New ticket creation
- Any update on a ticket
- 24-hour reminder when Inditech has not checked the ticket
- Auto-close after 7 days if Inditech completed it but client did not close it
- Daily summary for relevant Inditech users

Emails include:

- ticket details
- requester details
- current status values
- assigned Inditech user
- project manager
- latest update message
- attachment links

## Cron / Automation Command

The management command is:

```bash
DJANGO_SETTINGS_MODULE=task_manage.settings python manage.py run_client_ticket_automation
```

### Run everything

```bash
cd /path/to/Ticketing_System/task_manage
DJANGO_SETTINGS_MODULE=task_manage.settings python manage.py run_client_ticket_automation
```

This runs:

- unchecked ticket reminders
- stale ticket auto-close
- daily summary emails

### Run only reminders

```bash
DJANGO_SETTINGS_MODULE=task_manage.settings python manage.py run_client_ticket_automation --reminders-only
```

### Run only daily summaries

```bash
DJANGO_SETTINGS_MODULE=task_manage.settings python manage.py run_client_ticket_automation --summaries-only
```

### Run only auto-close

```bash
DJANGO_SETTINGS_MODULE=task_manage.settings python manage.py run_client_ticket_automation --auto-close-only
```

## Example Cron Entries

Every hour for unchecked reminders:

```cron
0 * * * * cd /var/www/Ticketing_System/task_manage && DJANGO_SETTINGS_MODULE=task_manage.settings /path/to/venv/bin/python manage.py run_client_ticket_automation --reminders-only >> /var/log/client_ticket_reminders.log 2>&1
```

Every day at 9:00 AM for summaries:

```cron
0 9 * * * cd /var/www/Ticketing_System/task_manage && DJANGO_SETTINGS_MODULE=task_manage.settings /path/to/venv/bin/python manage.py run_client_ticket_automation --summaries-only >> /var/log/client_ticket_summary.log 2>&1
```

Every day at 1:00 AM for auto-close:

```cron
0 1 * * * cd /var/www/Ticketing_System/task_manage && DJANGO_SETTINGS_MODULE=task_manage.settings /path/to/venv/bin/python manage.py run_client_ticket_automation --auto-close-only >> /var/log/client_ticket_autoclose.log 2>&1
```

## Recommended Environment Variables

For production, set at least:

```bash
export CLIENT_TICKETS_BASE_URL="https://your-domain.com"
export CLIENT_TICKETS_API_TOKEN="your-shared-secret"
```

`CLIENT_TICKETS_BASE_URL` is used in ticket emails so links point to the correct domain.
