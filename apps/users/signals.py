"""
У каждого пользователя есть профиль: он создаётся сразу при создании пользователя.

Обработчик объявлен на уровне модуля. Раньше он жил внутри UsersConfig.ready, и
сигнал держал его по слабой ссылке: функция исчезала со сборкой мусора, профиль
то создавался, то нет, а вход по OTP падал на повторном Profile.objects.create.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomUser, Profile


@receiver(post_save, sender=CustomUser)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
