import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

app = Celery('synth_share')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

from celery.schedules import crontab

app.conf.beat_schedule = {
    'notify_expiring_bookings_daily': {
        'task': 'apps.bookings.tasks.notify_expiring_bookings',
        'schedule': crontab(hour=10, minute=0),  # Everyday at 10:00 
    },
    'auto_complete_inspections_hourly': {
        'task': 'apps.bookings.tasks.auto_complete_inspections',
        'schedule': crontab(minute=0),  # Every top of the hour
    },
}
