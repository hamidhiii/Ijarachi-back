import django_filters
from math import cos, radians
from django.db.models import Q
from .models import Item


class ItemFilter(django_filters.FilterSet):
    min_price = django_filters.NumberFilter(field_name='price_per_day', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='price_per_day', lookup_expr='lte')
    price_min = django_filters.NumberFilter(field_name='price_per_day', lookup_expr='gte')
    price_max = django_filters.NumberFilter(field_name='price_per_day', lookup_expr='lte')
    category = django_filters.NumberFilter(field_name='category__id')
    category_slug = django_filters.CharFilter(field_name='category__slug')
    city = django_filters.CharFilter(field_name='city', lookup_expr='icontains')
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
            'city',
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
