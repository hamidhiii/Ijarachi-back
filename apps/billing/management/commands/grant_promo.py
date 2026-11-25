from django.core.management.base import BaseCommand

from apps.billing.promo import grant_everyone, promo_ends_at


class Command(BaseCommand):
    help = 'Выдать тариф по акции всем активным пользователям без оплаченного тарифа (и привести старые подарки к текущим условиям).'

    def handle(self, *args, **options):
        count = grant_everyone()
        self.stdout.write(f'promo granted/updated: {count}, ends {promo_ends_at()}')
