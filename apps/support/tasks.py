from celery import shared_task


@shared_task
def remind_waiting_tickets():
    from .telegram import remind_waiting

    return remind_waiting()
