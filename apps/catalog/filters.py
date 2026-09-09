import django_filters
from math import cos, radians
from django.db.models import Q
from .models import Item


def filter_by_attributes(queryset, query_params):
    """
    ?attr__<key>=<value>, повторяемый — «или» внутри одного ключа, «и» между
    разными ключами. Значение может быть скаляром (attributes={"height": 170})
    или элементом списка (attributes={"size": ["42","44"]}) — chips/select
    хранятся по-разному, поэтому пробуем оба варианта плюс числовой каст,
    т.к. number-атрибуты лежат в JSON как int/float, а из URL всегда строка.
    """
    attr_keys = {key for key in query_params if key.startswith('attr__')}
    for key in attr_keys:
        attr_name = key[len('attr__'):]
        if not attr_name:
            continue
        values = query_params.getlist(key)
        if not values:
            continue
        or_q = Q()
        for value in values:
            or_q |= Q(**{f'attributes__{attr_name}': value})
            or_q |= Q(**{f'attributes__{attr_name}__contains': value})
            try:
                numeric = float(value) if '.' in value else int(value)
            except ValueError:
                numeric = None
            if numeric is not None:
                or_q |= Q(**{f'attributes__{attr_name}': numeric})
        queryset = queryset.filter(or_q)
    return queryset


class ItemFilter(django_filters.FilterSet):
    min_price = django_filters.NumberFilter(field_name='price_per_day', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='price_per_day', lookup_expr='lte')
    price_min = django_filters.NumberFilter(field_name='price_per_day', lookup_expr='gte')
    price_max = django_filters.NumberFilter(field_name='price_per_day', lookup_expr='lte')
    category = django_filters.NumberFilter(field_name='category__id')
    category_slug = django_filters.CharFilter(field_name='category__slug')
    owner = django_filters.NumberFilter(field_name='owner__id')
    owner_id = django_filters.NumberFilter(field_name='owner__id')
    city = django_filters.CharFilter(field_name='city', lookup_expr='icontains')
    district = django_filters.CharFilter(field_name='district', lookup_expr='icontains')
    condition = django_filters.ChoiceFilter(choices=Item.CONDITION_CHOICES)
    radius = django_filters.NumberFilter(method='filter_radius')

    class Meta:
        model = Item
        fields = [
            'min_price',
            'max_price',
            'price_min',
            'price_max',
            'category',
            'category_slug',
            'owner',
            'owner_id',
            'city',
            'district',
            'condition',
            'radius',
        ]

    def filter_radius(self, queryset, name, value):
        lat = self.request.query_params.get('lat') if self.request else None
        lng = self.request.query_params.get('lng') if self.request else None
        if not lat or not lng or not value:
            return queryset
        try:
            lat = float(lat)
            lng = float(lng)
            radius_km = float(value)
        except (TypeError, ValueError):
            return queryset.none()

        lat_delta = radius_km / 111.0
        lng_delta = radius_km / max(1.0, 111.0 * abs(cos(radians(lat))))
        return queryset.filter(
            Q(latitude__gte=lat - lat_delta) &
            Q(latitude__lte=lat + lat_delta) &
            Q(longitude__gte=lng - lng_delta) &
            Q(longitude__lte=lng + lng_delta)
        )
