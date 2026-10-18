from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Category, Item, ItemImage

SEED_DIR = Path(__file__).resolve().parents[2] / 'seed_images'

# По одному объявлению на категорию — чтобы витрина не была пустой. Фото —
# иллюстрации категорий из apps/catalog/seed_images/<slug>.jpg. Это
# заготовки: владелец правит цену, описание и фото в «Мои объявления».
DEMO = [
    ('platya-i-naryady', 'Вечернее платье, изумрудный шёлк',
     'Длинное вечернее платье изумрудного цвета, в комплекте пояс. Чистое, после химчистки. '
     'Примерка по записи.', 350_000, 'excellent', True),
    ('kostyumy-i-aksessuary', 'Мужской смокинг с бабочкой и ремнём',
     'Тёмно-зелёный смокинг, рубашка, бабочка и ремень. Подгонка по размеру при самовывозе.',
     300_000, 'excellent', False),
    ('zvukovoe-oborudovanie', 'Колонки и микшерный пульт для мероприятия',
     'Две активные колонки, микшер и проводной микрофон. Подходит для зала до 100 человек.',
     400_000, 'good', True),
    ('svetovoe-oborudovanie', 'Сценические прожекторы, комплект из 4 шт.',
     'Четыре световых прибора на стойке, управление с пульта. Помогу с настройкой при выдаче.',
     450_000, 'good', False),
    ('foto-video-oborudovanie', 'Видеокамера со штативом на сутки',
     'Профессиональная видеокамера, штатив и две батареи. Для свадьбы или съёмки мероприятия.',
     500_000, 'excellent', True),
    ('svadebny-dekor', 'Свадебная арка с живыми цветами',
     'Арка с драпировкой и цветочным оформлением. Доставка и установка обсуждаются отдельно.',
     800_000, 'excellent', True),
    ('posuda', 'Набор посуды на 12 персон',
     'Тарелки, бокалы и столовые приборы на 12 человек. Всё чистое, в коробках.',
     150_000, 'good', False),
    ('skaterty-i-tekstil', 'Скатерти и салфетки, изумрудный набор',
     'Комплект скатертей и тканевых салфеток в изумрудных и кремовых тонах. Выглажено.',
     120_000, 'excellent', False),
    ('tent-i-shater', 'Свадебный шатёр 6×12 м',
     'Каркасный шатёр с белым тентом на 80 гостей. Монтаж силами владельца за отдельную плату.',
     1_500_000, 'good', True),
    ('mebel-stoly-stulya', 'Банкетные стулья и круглый стол',
     'Круглый стол на 10 мест, скатерть в комплекте, зелёные мягкие стулья. Есть 10 штук.',
     250_000, 'good', False),
]


class Command(BaseCommand):
    help = (
        'Creates one approved demo listing per category (photo from '
        'apps/catalog/seed_images). Safe to re-run: a listing with the same '
        'title and owner is left alone.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--owner-phone',
            help='Phone of the existing account that will own the listings, e.g. +998901234567. '
                 'Defaults to the first superuser.',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        phone = options.get('owner_phone')
        owner = (
            User.objects.filter(phone=phone).first() if phone
            else User.objects.filter(is_superuser=True).order_by('id').first()
        )
        if not owner:
            raise CommandError('Owner not found: pass --owner-phone of an existing account.')

        created = 0
        for slug, title, description, price, condition, negotiable in DEMO:
            category = Category.objects.filter(slug=slug).first()
            if not category:
                self.stdout.write(self.style.WARNING(f'skip {slug}: category does not exist'))
                continue
            if Item.objects.filter(owner=owner, title=title).exists():
                self.stdout.write(f'exists: {title}')
                continue

            photo = SEED_DIR / f'{slug}.jpg'
            if not photo.exists():
                self.stdout.write(self.style.WARNING(f'skip {slug}: no {photo.name}'))
                continue

            item = Item.objects.create(
                owner=owner,
                category=category,
                title=title,
                description=description,
                price_per_day=price,
                condition=condition,
                status=Item.STATUS_APPROVED,
                is_negotiable=negotiable,
                address='Ташкент, Юнусабад',
                city='Ташкент',
                district='Юнусабад',
            )
            image = ItemImage(item=item, is_primary=True)
            image.image.save(f'{slug}.jpg', ContentFile(photo.read_bytes()), save=True)
            created += 1
            self.stdout.write(self.style.SUCCESS(f'created: {title}'))

        self.stdout.write(self.style.SUCCESS(f'Done — {created} new listing(s).'))
