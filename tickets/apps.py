import os
from django.apps import AppConfig


class TicketsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tickets'

    def ready(self):
        import tickets.signals  # noqa: F401

        # Start background automation only in the main process (not in migrate/shell/etc.)
        # RUN_MAIN is set by Django's auto-reloader — ensures we only start once.
        if os.environ.get('RUN_MAIN') == 'true':
            from .automation import start_automation
            start_automation()
