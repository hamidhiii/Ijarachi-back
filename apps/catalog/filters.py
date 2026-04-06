import django_filters
from .models import Item


class ItemFilter(django_filters.FilterSet):
    min_price = django_filters.NumberFilter(field_name='price_per_day', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='price_per_day', lookup_expr='lte')
    category = django_filters.NumberFilter(field_name='category__id')
    category_slug = django_filters.CharFilter(field_name='category__slug')
    city = django_filters.CharFilter(field_name='city', lookup_expr='icontains')
    condition = django_filters.ChoiceFilter(choices=Item.CONDITION_CHOICES)

    class Meta:
        model = Item
        fields = ['min_price', 'max_price', 'category', 'category_slug', 'city', 'condition']
