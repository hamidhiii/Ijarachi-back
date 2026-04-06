from django.core.management.base import BaseCommand
from apps.catalog.models import Category


CATEGORIES = {
    'name': 'Той и праздники',
    'slug': 'toy-i-prazdniki',
    'icon': '🎉',
    'children': [
        {'name': 'Свадебный декор', 'slug': 'svadebny-dekor', 'icon': '💍'},
        {'name': 'Платья и наряды', 'slug': 'platya-i-naryady', 'icon': '👗'},
        {'name': 'Посуда', 'slug': 'posuda', 'icon': '🍽️'},
        {'name': 'Скатерти и текстиль', 'slug': 'skaterty-i-tekstil', 'icon': '🪡'},
        {'name': 'Тент и шатёр', 'slug': 'tent-i-shater', 'icon': '⛺'},
        {'name': 'Мебель (столы, стулья)', 'slug': 'mebel-stoly-stulya', 'icon': '🪑'},
        {'name': 'Звуковое оборудование', 'slug': 'zvukovoe-oborudovanie', 'icon': '🎤'},
        {'name': 'Световое оборудование', 'slug': 'svetovoe-oborudovanie', 'icon': '💡'},
        {'name': 'Фото и видео оборудование', 'slug': 'foto-video-oborudovanie', 'icon': '📷'},
        {'name': 'Костюмы и аксессуары', 'slug': 'kostyumy-i-aksessuary', 'icon': '🎭'},
    ]
}


class Command(BaseCommand):
    help = 'Засеивает базу категориями для раздела "Той и праздники"'

    def handle(self, *args, **options):
        parent, created = Category.objects.get_or_create(
            slug=CATEGORIES['slug'],
            defaults={
                'name': CATEGORIES['name'],
                'icon': CATEGORIES['icon'],
                'is_active': True,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Создана родительская категория: {parent.name}'))
        else:
            self.stdout.write(f'  Категория уже существует: {parent.name}')

        for child_data in CATEGORIES['children']:
            child, created = Category.objects.get_or_create(
                slug=child_data['slug'],
                defaults={
                    'name': child_data['name'],
                    'icon': child_data['icon'],
                    'parent': parent,
                    'is_active': True,
                }
            )
            status = '✓ Создана' if created else '  Уже есть'
            self.stdout.write(f'{status}: {child.name}')

        self.stdout.write(self.style.SUCCESS('\n✅ Категории успешно засеяны!'))
