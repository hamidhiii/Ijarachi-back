from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import Category, Item, ItemImage, ItemAvailability
from .serializers import (
    CategorySerializer,
    ItemListSerializer,
    ItemDetailSerializer,
    ItemCreateSerializer,
    ItemUpdateSerializer,
    ItemImageSerializer,
    ItemImageUploadSerializer,
)
from .filters import ItemFilter


class CategoryListView(generics.ListAPIView):
    """
    GET /api/v1/categories/
    Возвращает дерево категорий (только корневые с детьми).
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = CategorySerializer
    pagination_class = None

    def get_queryset(self):
        return Category.objects.filter(
            is_active=True, parent__isnull=True
        ).prefetch_related('children')


class ItemListView(generics.ListAPIView):
    """
    GET /api/v1/catalog/
    Список активных объявлений с фильтрацией и поиском.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = ItemListSerializer
    filterset_class = ItemFilter
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['title', 'description', 'city']
    ordering_fields = ['price_per_day', 'created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        return (
            Item.objects
            .filter(status=Item.STATUS_ACTIVE)
            .select_related('category', 'owner__profile')
            .prefetch_related('images')
        )


class ItemDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/catalog/{id}/
    Полная карточка вещи с заблокированными датами.
    """
    permission_classes = [permissions.AllowAny]
    serializer_class = ItemDetailSerializer

    def get_queryset(self):
        return (
            Item.objects
            .filter(status=Item.STATUS_ACTIVE)
            .select_related('category', 'owner__profile', 'availability')
            .prefetch_related('images')
        )


class ItemCreateView(generics.CreateAPIView):
    """
    POST /api/v1/items/create/
    Создание нового объявления (требует JWT).
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ItemCreateSerializer

    def perform_create(self, serializer):
        serializer.save()


class MyItemsView(generics.ListAPIView):
    """
    GET /api/v1/items/my/
    Мои объявления (все статусы).
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ItemListSerializer

    def get_queryset(self):
        return (
            Item.objects
            .filter(owner=self.request.user)
            .select_related('category', 'owner__profile')
            .prefetch_related('images')
        )


class ItemUpdateView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /api/v1/items/{id}/
    Редактирование/удаление своего объявления.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ItemUpdateSerializer

    def get_queryset(self):
        return Item.objects.filter(owner=self.request.user)

    def perform_destroy(self, instance):
        # Soft-delete: set inactive
        instance.status = Item.STATUS_INACTIVE
        instance.save(update_fields=['status'])


class ItemImageUploadView(APIView):
    """
    POST /api/v1/items/{item_id}/images/
    Загрузка фото к объявлению.
    DELETE /api/v1/items/{item_id}/images/{image_id}/
    Удаление фото.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _get_item(self, item_id, user):
        try:
            return Item.objects.get(pk=item_id, owner=user)
        except Item.DoesNotExist:
            return None

    def post(self, request, item_id):
        item = self._get_item(item_id, request.user)
        if not item:
            return Response({'detail': 'Объявление не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        if item.images.count() >= 10:
            return Response({'detail': 'Максимум 10 фото.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ItemImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image = serializer.save(item=item)
        return Response(ItemImageSerializer(image).data, status=status.HTTP_201_CREATED)

    def delete(self, request, item_id, image_id):
        item = self._get_item(item_id, request.user)
        if not item:
            return Response({'detail': 'Объявление не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            image = item.images.get(pk=image_id)
        except ItemImage.DoesNotExist:
            return Response({'detail': 'Фото не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        was_primary = image.is_primary
        image.delete()

        # Reassign primary if deleted
        if was_primary:
            first = item.images.first()
            if first:
                first.is_primary = True
                first.save(update_fields=['is_primary'])

        return Response(status=status.HTTP_204_NO_CONTENT)
