from .services import auto_close_stale_tickets, send_daily_summary_emails, send_unchecked_ticket_reminders


def run_client_ticket_automation():
    return {
        "unchecked_reminders_sent": send_unchecked_ticket_reminders(),
        "auto_closed_tickets": auto_close_stale_tickets(),
        "summary_emails_sent": send_daily_summary_emails(),
    }
