from django.core.management.base import BaseCommand
from apps.catalog.models import Category


# name_uz — черновой перевод, правится в админке (Категории → Название (uz)).
CATEGORIES = {
    'name': 'Той и праздники',
    'name_uz': "To'y va bayramlar",
    'slug': 'toy-i-prazdniki',
    'icon': '🎉',
    'children': [
        {'name': 'Свадебный декор', 'name_uz': "To'y bezaklari", 'slug': 'svadebny-dekor', 'icon': '💍'},
        {'name': 'Платья и наряды', 'name_uz': "Ko'ylak va liboslar", 'slug': 'platya-i-naryady', 'icon': '👗'},
        {'name': 'Посуда', 'name_uz': 'Idish-tovoq', 'slug': 'posuda', 'icon': '🍽️'},
        {'name': 'Скатерти и текстиль', 'name_uz': "Dasturxon va to'qimachilik", 'slug': 'skaterty-i-tekstil', 'icon': '🪡'},
        {'name': 'Тент и шатёр', 'name_uz': 'Tent va chodir', 'slug': 'tent-i-shater', 'icon': '⛺'},
        {'name': 'Мебель (столы, стулья)', 'name_uz': 'Mebel (stol, stul)', 'slug': 'mebel-stoly-stulya', 'icon': '🪑'},
        {'name': 'Звуковое оборудование', 'name_uz': 'Ovoz uskunalari', 'slug': 'zvukovoe-oborudovanie', 'icon': '🎤'},
        {'name': 'Световое оборудование', 'name_uz': "Yorug'lik uskunalari", 'slug': 'svetovoe-oborudovanie', 'icon': '💡'},
        {'name': 'Фото и видео оборудование', 'name_uz': 'Foto va video uskunalar', 'slug': 'foto-video-oborudovanie', 'icon': '📷'},
        {'name': 'Костюмы и аксессуары', 'name_uz': 'Kostyum va aksessuarlar', 'slug': 'kostyumy-i-aksessuary', 'icon': '🎭'},
    ]
}


class Command(BaseCommand):
    help = 'Засеивает базу категориями для раздела "Той и праздники"'

    def handle(self, *args, **options):
        parent, created = Category.objects.get_or_create(
            slug=CATEGORIES['slug'],
            defaults={
                'name': CATEGORIES['name'],
                'name_uz': CATEGORIES['name_uz'],
                'icon': CATEGORIES['icon'],
                'is_active': True,
            }
        )
        self._fill_name_uz(parent, CATEGORIES['name_uz'])
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Создана родительская категория: {parent.name}'))
        else:
            self.stdout.write(f'  Категория уже существует: {parent.name}')

        for child_data in CATEGORIES['children']:
            child, created = Category.objects.get_or_create(
                slug=child_data['slug'],
                defaults={
                    'name': child_data['name'],
                    'name_uz': child_data['name_uz'],
                    'icon': child_data['icon'],
                    'parent': parent,
                    'is_active': True,
                }
            )
            self._fill_name_uz(child, child_data['name_uz'])
            status = '✓ Создана' if created else '  Уже есть'
            self.stdout.write(f'{status}: {child.name}')

        self.stdout.write(self.style.SUCCESS('\n✅ Категории успешно засеяны!'))

    def _fill_name_uz(self, category, name_uz):
        # Категории, засеянные до появления name_uz, дополняем переводом,
        # но уже заполненное вручную значение не трогаем.
        if not category.name_uz and name_uz:
            category.name_uz = name_uz
            category.save(update_fields=['name_uz'])
