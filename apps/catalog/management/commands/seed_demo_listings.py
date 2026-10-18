import urllib.request

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Category, Item, ItemImage

# По одному объявлению на категорию — чтобы витрина не была пустой. Фото —
# настоящие снимки предметов с Unsplash (бесплатная лицензия, атрибуция не
# нужна); команда скачивает их при запуске на сервере. Это заготовки:
# владелец правит цену, описание и фото в «Мои объявления».
PHOTO_URL = 'https://images.unsplash.com/photo-{id}?auto=format&fit=crop&w=1200&q=80'

# (slug, заголовок, описание, цена, состояние, торг, id снимка на Unsplash)
DEMO = [
    ('platya-i-naryady', 'Вечернее платье с вышивкой, бордо',
     'Длинное вечернее платье из тюля с вышивкой, цвет бордо. Чистое, после химчистки. '
     'Примерка по записи.', 350_000, 'excellent', True, '1568252542512-9fe8fe9c87bb'),
    ('kostyumy-i-aksessuary', 'Мужской смокинг с бабочкой',
     'Чёрный смокинг, рубашка и бабочка. Подгонка по размеру при самовывозе.',
     300_000, 'excellent', False, '1522968439036-e6338d0ed84f'),
    ('zvukovoe-oborudovanie', 'Акустические колонки для мероприятия',
     'Две активные колонки с подставками. Подходит для зала до 100 человек.',
     400_000, 'good', True, '1561314105-e6ac04c2984a'),
    ('svetovoe-oborudovanie', 'Сценический свет: прожекторы и лазеры',
     'Комплект приборов для светового шоу, управление с пульта. Помогу с настройкой при выдаче.',
     450_000, 'good', False, '1599739291060-4578e77dac5d'),
    ('foto-video-oborudovanie', 'Видеокамера со штативом на сутки',
     'Профессиональная видеокамера на штативе, две батареи. Для свадьбы или съёмки мероприятия.',
     500_000, 'excellent', True, '1612548403247-aa2873e9422d'),
    ('svadebny-dekor', 'Цветочное оформление свадебной церемонии',
     'Композиции из живых цветов вдоль дорожки и у арки. Доставка и установка — отдельно.',
     800_000, 'excellent', True, '1469371670807-013ccf25f16a'),
    ('posuda', 'Набор винтажных тарелок на 12 персон',
     'Фарфоровые тарелки разных размеров на 12 человек. Всё чистое, в коробках.',
     150_000, 'good', False, '1551807306-4bcd16b92a41'),
    ('skaterty-i-tekstil', 'Льняные скатерти и полотенца, натуральные тона',
     'Комплект льняного текстиля в бежевых тонах. Выглажено, упаковано.',
     120_000, 'excellent', False, '1591625591034-75d303d2e1a4'),
    ('tent-i-shater', 'Белый шатёр для свадьбы и банкета',
     'Каркасный шатёр с белым тентом на 80 гостей. Монтаж силами владельца за отдельную плату.',
     1_500_000, 'good', True, '1675376616537-c8aa9ddc9977'),
    ('mebel-stoly-stulya', 'Деревянный стол и стулья для банкета',
     'Длинный деревянный стол и плетёные стулья, есть 10 штук. Самовывоз.',
     250_000, 'good', False, '1696805966408-5f92fdb79ae7'),
]


def download(photo_id):
    request = urllib.request.Request(
        PHOTO_URL.format(id=photo_id), headers={'User-Agent': 'rentoo-seed/1.0'}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


class Command(BaseCommand):
    help = (
        'Creates one approved demo listing per category with a real photograph '
        '(downloaded from Unsplash). Safe to re-run: a listing with the same '
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
        for slug, title, description, price, condition, negotiable, photo_id in DEMO:
            category = Category.objects.filter(slug=slug).first()
            if not category:
                self.stdout.write(self.style.WARNING(f'skip {slug}: category does not exist'))
                continue
            if Item.objects.filter(owner=owner, title=title).exists():
                self.stdout.write(f'exists: {title}')
                continue

            # The photograph first: a listing with no picture is worse than none.
            try:
                photo = download(photo_id)
            except Exception as exc:  # network, 404, timeout
                self.stdout.write(self.style.WARNING(f'skip {slug}: photo not downloaded ({exc})'))
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
            image.image.save(f'{slug}.jpg', ContentFile(photo), save=True)
            created += 1
            self.stdout.write(self.style.SUCCESS(f'created: {title}'))

        self.stdout.write(self.style.SUCCESS(f'Done — {created} new listing(s).'))
