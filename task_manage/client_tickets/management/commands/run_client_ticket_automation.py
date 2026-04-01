from django.core.management.base import BaseCommand

from client_tickets.services import auto_close_stale_tickets, send_daily_summary_emails, send_unchecked_ticket_reminders
from client_tickets.tasks import run_client_ticket_automation


class Command(BaseCommand):
    help = "Run client ticket reminder, auto-close, and daily summary automation."

    def add_arguments(self, parser):
        parser.add_argument("--reminders-only", action="store_true", help="Send 24-hour unchecked ticket reminders only.")
        parser.add_argument("--summaries-only", action="store_true", help="Send daily client ticket summaries only.")
        parser.add_argument("--auto-close-only", action="store_true", help="Auto close stale tickets only.")

    def handle(self, *args, **options):
        selected_modes = [
            options.get("reminders_only"),
            options.get("summaries_only"),
            options.get("auto_close_only"),
        ]
        if sum(bool(mode) for mode in selected_modes) > 1:
            self.stderr.write("Choose only one of --reminders-only, --summaries-only, or --auto-close-only.")
            return

        if options.get("reminders_only"):
            results = {"unchecked_reminders_sent": send_unchecked_ticket_reminders()}
        elif options.get("summaries_only"):
            results = {"summary_emails_sent": send_daily_summary_emails()}
        elif options.get("auto_close_only"):
            results = {"auto_closed_tickets": auto_close_stale_tickets()}
        else:
            results = run_client_ticket_automation()
        for key, value in results.items():
            self.stdout.write(f"{key}: {value}")
