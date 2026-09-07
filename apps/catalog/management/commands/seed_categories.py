from django.core.management.base import BaseCommand
from apps.catalog.models import Category


COLOR_OPTIONS = [
    'белый', 'айвори', 'золотой', 'серебряный', 'чёрный',
    'красный', 'синий', 'зелёный', 'розовый',
]
OPERATOR_OPTIONS = ['входит в стоимость', 'оплачивается отдельно', 'не требуется']
SETUP_OPTIONS = ['входит в стоимость', 'оплачивается отдельно', 'самовывоз без установки']

# Определения полей формы размещения по slug категории (см. backend-integration
# doc "Характеристики объявления"). Источник истины для Category.attributes —
# используется и здесь (для свежих БД), и миграцией apps.catalog.migrations.
# 0006_attributes (бэкофилл для БД, где категории уже существовали).
CATEGORY_ATTRIBUTES = {
    'platya-i-naryady': [
        {'key': 'size', 'label': 'Размер', 'type': 'chips',
         'options': ['40', '42', '44', '46', '48', '50', '52', '54', '56']},
        {'key': 'height', 'label': 'Рост модели', 'type': 'number', 'unit': 'см'},
        {'key': 'color', 'label': 'Цвет', 'type': 'chips', 'options': COLOR_OPTIONS},
        {'key': 'material', 'label': 'Материал', 'type': 'text'},
        {'key': 'fitting', 'label': 'Примерка', 'type': 'select',
         'options': ['возможна', 'только по записи', 'не проводится']},
    ],
    'kostyumy-i-aksessuary': [
        {'key': 'size', 'label': 'Размер', 'type': 'chips',
         'options': ['40', '42', '44', '46', '48', '50', '52', '54', '56']},
        {'key': 'gender', 'label': 'Для кого', 'type': 'select',
         'options': ['мужской', 'женский', 'детский', 'унисекс']},
        {'key': 'color', 'label': 'Цвет', 'type': 'chips', 'options': COLOR_OPTIONS},
        {'key': 'kit', 'label': 'Что входит в комплект', 'type': 'text'},
    ],
    'mebel-stoly-stulya': [
        {'key': 'quantity', 'label': 'Количество', 'type': 'number', 'unit': 'шт'},
        {'key': 'seats', 'label': 'Посадочных мест', 'type': 'number', 'unit': 'чел'},
        {'key': 'dimensions', 'label': 'Габариты', 'type': 'text'},
        {'key': 'material', 'label': 'Материал', 'type': 'select',
         'options': ['дерево', 'металл', 'пластик', 'ротанг', 'стекло']},
    ],
    'posuda': [
        {'key': 'persons', 'label': 'На сколько персон', 'type': 'number', 'unit': 'чел'},
        {'key': 'pieces', 'label': 'Предметов в наборе', 'type': 'number', 'unit': 'шт'},
        {'key': 'material', 'label': 'Материал', 'type': 'select',
         'options': ['фарфор', 'керамика', 'стекло', 'нержавеющая сталь', 'серебро', 'мельхиор']},
    ],
    'skaterty-i-tekstil': [
        {'key': 'quantity', 'label': 'Количество', 'type': 'number', 'unit': 'шт'},
        {'key': 'dimensions', 'label': 'Размер', 'type': 'text'},
        {'key': 'color', 'label': 'Цвет', 'type': 'chips', 'options': COLOR_OPTIONS},
        {'key': 'material', 'label': 'Материал', 'type': 'text'},
    ],
    'tent-i-shater': [
        {'key': 'dimensions', 'label': 'Размер', 'type': 'text'},
        {'key': 'capacity', 'label': 'Вместимость', 'type': 'number', 'unit': 'чел'},
        {'key': 'setup', 'label': 'Монтаж', 'type': 'select', 'options': SETUP_OPTIONS},
        {'key': 'flooring', 'label': 'Настил пола', 'type': 'select', 'options': ['есть', 'нет']},
    ],
    'svadebny-dekor': [
        {'key': 'quantity', 'label': 'Количество', 'type': 'number', 'unit': 'шт'},
        {'key': 'color', 'label': 'Цвет', 'type': 'chips', 'options': COLOR_OPTIONS},
        {'key': 'style', 'label': 'Стиль', 'type': 'select',
         'options': ['классический', 'современный', 'национальный', 'рустик', 'минимализм']},
        {'key': 'setup', 'label': 'Установка', 'type': 'select', 'options': SETUP_OPTIONS},
    ],
    'toy-i-prazdniki': [
        {'key': 'quantity', 'label': 'Количество', 'type': 'number', 'unit': 'шт'},
        {'key': 'guests', 'label': 'На сколько гостей', 'type': 'number', 'unit': 'чел'},
        {'key': 'kit', 'label': 'Что входит в комплект', 'type': 'text'},
    ],
    'zvukovoe-oborudovanie': [
        {'key': 'power', 'label': 'Мощность', 'type': 'number', 'unit': 'Вт'},
        {'key': 'area', 'label': 'На площадь до', 'type': 'number', 'unit': 'м²'},
        {'key': 'kit', 'label': 'Что входит в комплект', 'type': 'text'},
        {'key': 'operator', 'label': 'Оператор', 'type': 'select', 'options': OPERATOR_OPTIONS},
    ],
    'svetovoe-oborudovanie': [
        {'key': 'quantity', 'label': 'Количество приборов', 'type': 'number', 'unit': 'шт'},
        {'key': 'power', 'label': 'Мощность', 'type': 'number', 'unit': 'Вт'},
        {'key': 'kit', 'label': 'Что входит в комплект', 'type': 'text'},
        {'key': 'operator', 'label': 'Оператор', 'type': 'select', 'options': OPERATOR_OPTIONS},
    ],
    'foto-video-oborudovanie': [
        {'key': 'model', 'label': 'Модель', 'type': 'text'},
        {'key': 'kit', 'label': 'Что входит в комплект', 'type': 'text'},
        {'key': 'pledge_document', 'label': 'Залоговый документ', 'type': 'select',
         'options': ['паспорт', 'водительские права', 'не требуется']},
        {'key': 'operator', 'label': 'Оператор', 'type': 'select', 'options': OPERATOR_OPTIONS},
    ],
}

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
    help = 'Засеивает базу категориями для раздела "Той и праздники" и их attributes'

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
        self._fill_attributes(parent)
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
            self._fill_attributes(child)
            status = '✓ Создана' if created else '  Уже есть'
            self.stdout.write(f'{status}: {child.name}')

        self.stdout.write(self.style.SUCCESS('\n✅ Категории успешно засеяны!'))

    def _fill_name_uz(self, category, name_uz):
        # Категории, засеянные до появления name_uz, дополняем переводом,
        # но уже заполненное вручную значение не трогаем.
        if not category.name_uz and name_uz:
            category.name_uz = name_uz
            category.save(update_fields=['name_uz'])

    def _fill_attributes(self, category):
        # Тот же принцип: заполняем, только если категория ещё без своих
        # полей формы — правки, сделанные вручную в админке, не перетираем.
        attributes = CATEGORY_ATTRIBUTES.get(category.slug)
        if attributes and not category.attributes:
            category.attributes = attributes
            category.save(update_fields=['attributes'])
