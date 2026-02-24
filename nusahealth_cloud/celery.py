"""
NusaHealth Cloud — Celery Configuration
With Celery Beat schedule for periodic forecast training and report generation.
"""

import os
import sys
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nusahealth_cloud.settings")

app = Celery("nusahealth_cloud")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# ── Celery Beat Schedule ─────────────────────────────────────────────
app.conf.beat_schedule = {
    # Train LightGBM forecast models every Monday at 3:00 AM
    "train-forecast-models-weekly": {
        "task": "reports.tasks.train_forecast_models",
        "schedule": crontab(hour=3, minute=0, day_of_week=1),  # Monday 03:00
    },
    # Generate monthly village report on 1st of each month at 6:00 AM
    "generate-monthly-report": {
        "task": "reports.tasks.generate_monthly_report",
        "schedule": crontab(hour=6, minute=0, day_of_month=1),  # 1st of month 06:00
    },
}
app.conf.timezone = "Asia/Jakarta"

# Log Windows pool warning
if sys.platform == "win32":
    import logging
    logging.getLogger("nusahealth").info(
        "Windows detected — Celery will use 'solo' pool. "
        "This is fine for development. Production on Linux uses 'prefork'."
    )


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
