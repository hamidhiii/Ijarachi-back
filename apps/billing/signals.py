from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def signup_promo(sender, instance, created, **kwargs):
    """Новый пользователь — подарок по акции, после коммита регистрации (сбой не мешает входу)."""
    if not created:
        return

    def grant():
        from .promo import grant_signup_promo

        try:
            grant_signup_promo(instance)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger('apps.billing').exception('Signup promo failed for user %s', instance.pk)

    transaction.on_commit(grant)
