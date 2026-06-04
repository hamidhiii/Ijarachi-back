from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import connection
from django.db.models import F, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import Category, Favorite, Item, ItemImage, ItemAvailability
from .serializers import (
    CategorySerializer,
    ItemListSerializer,
    ItemDetailSerializer,
    ItemCreateSerializer,
    ItemUpdateSerializer,
    ItemImageSerializer,
    ItemImageUploadSerializer,
    FavoriteCreateSerializer,
    FavoriteSerializer,
    ListingAvailabilitySerializer,
    ListingModerationSerializer,
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


class ListingListCreateView(generics.ListCreateAPIView):
    """
    GET/POST /api/v1/listings/
    """
    filterset_class = ItemFilter
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['title', 'description', 'city']
    ordering_fields = ['price_per_day', 'created_at', 'view_count']
    ordering = ['-created_at']

    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ItemCreateSerializer
        return ItemListSerializer

    def get_queryset(self):
        qs = (
            Item.objects
            .filter(status=Item.STATUS_APPROVED)
            .select_related('category', 'owner__profile')
            .prefetch_related('images')
        )
        query = self.request.query_params.get('q')
        if query:
            if connection.vendor == 'postgresql':
                from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
                vector = SearchVector('title', weight='A') + SearchVector('description', weight='B')
                search_query = SearchQuery(query)
                qs = qs.annotate(rank=SearchRank(vector, search_query)).filter(rank__gt=0)
                if self.request.query_params.get('ordering') == 'relevance':
                    qs = qs.order_by('-rank')
            else:
                qs = qs.filter(Q(title__icontains=query) | Q(description__icontains=query))
        ordering = self.request.query_params.get('ordering')
        if ordering == 'date':
            qs = qs.order_by('-created_at')
        elif ordering == 'price':
            qs = qs.order_by('price_per_day')
        elif ordering == '-price':
            qs = qs.order_by('-price_per_day')
        return qs


class ItemListView(ListingListCreateView):
    """
    Backward compatible GET /api/v1/catalog/.
    """

    http_method_names = ['get', 'head', 'options']


class ListingDetailUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /api/v1/listings/{id}/
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.request.method in ['PATCH', 'PUT']:
            return ItemUpdateSerializer
        return ItemDetailSerializer

    def get_queryset(self):
        if self.request.method in ['PATCH', 'PUT', 'DELETE']:
            return Item.objects.filter(owner=self.request.user)
        return (
            Item.objects
            .filter(status=Item.STATUS_APPROVED)
            .select_related('category', 'owner__profile', 'availability')
            .prefetch_related('images')
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        Item.objects.filter(pk=instance.pk).update(view_count=F('view_count') + 1)
        instance.view_count += 1
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_destroy(self, instance):
        instance.status = Item.STATUS_INACTIVE
        instance.save(update_fields=['status'])


class ItemDetailView(ListingDetailUpdateDestroyView):
    """
    Backward compatible GET /api/v1/catalog/{id}/.
    """

    http_method_names = ['get', 'head', 'options']


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


class ListingStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        try:
            item = Item.objects.get(pk=pk, owner=request.user)
        except Item.DoesNotExist:
            return Response({'detail': 'Объявление не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'listing_id': item.pk,
            'views': item.view_count,
            'favorites': item.favorite_count,
            'deals': item.bookings.count(),
        })


class ListingAvailabilityView(APIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def _get_item(self, request, pk, write=False):
        qs = Item.objects.all()
        if write:
            qs = qs.filter(owner=request.user)
        elif not request.user.is_authenticated:
            qs = qs.filter(status=Item.STATUS_APPROVED)
        else:
            qs = qs.filter(Q(status=Item.STATUS_APPROVED) | Q(owner=request.user))
        try:
            return qs.get(pk=pk)
        except Item.DoesNotExist:
            return None

    def get(self, request, pk):
        item = self._get_item(request, pk)
        if not item:
            return Response({'detail': 'Объявление не найдено.'}, status=status.HTTP_404_NOT_FOUND)
        availability, _ = ItemAvailability.objects.get_or_create(item=item)
        return Response({
            'listing_id': item.pk,
            'blocked_dates': availability.blocked_dates,
            'blockedDates': availability.blocked_dates,
        })


class ListingReviewsView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]

    def get_serializer_class(self):
        from apps.bookings.serializers import DealReviewSerializer
        return DealReviewSerializer

    def get_queryset(self):
        from apps.bookings.models import DealReview
        return (
            DealReview.objects
            .filter(listing_id=self.kwargs['pk'], reviewee_id=F('listing__owner_id'))
            .select_related('booking', 'listing', 'reviewer__profile', 'reviewee__profile')
        )

    def patch(self, request, pk):
        item = self._get_item(request, pk, write=True)
        if not item:
            return Response({'detail': 'Объявление не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ListingAvailabilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        availability, _ = ItemAvailability.objects.get_or_create(item=item)
        availability.blocked_dates = serializer.validated_data['blocked_dates']
        availability.save(update_fields=['blocked_dates'])
        return Response({
            'listing_id': item.pk,
            'blocked_dates': availability.blocked_dates,
            'blockedDates': availability.blocked_dates,
        })


class ListingModerationView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, pk):
        try:
            item = Item.objects.get(pk=pk)
        except Item.DoesNotExist:
            return Response({'detail': 'Объявление не найдено.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ListingModerationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item.status = serializer.validated_data['status']
        item.rejection_reason = serializer.validated_data.get('rejection_reason', '')
        item.save(update_fields=['status', 'rejection_reason', 'updated_at'])
        return Response(ItemDetailSerializer(item, context={'request': request}).data)


class FavoriteListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = Favorite.objects.filter(user=request.user).select_related('item', 'item__category', 'item__owner__profile')
        return Response(FavoriteSerializer(qs, many=True, context={'request': request}).data)

    def post(self, request):
        serializer = FavoriteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        favorite, created = Favorite.objects.get_or_create(
            user=request.user,
            item=serializer.validated_data['item'],
        )
        if created:
            Item.objects.filter(pk=favorite.item_id).update(favorite_count=F('favorite_count') + 1)
            favorite.item.favorite_count += 1
        return Response(
            FavoriteSerializer(favorite, context={'request': request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class FavoriteDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, listing_id):
        deleted, _ = Favorite.objects.filter(user=request.user, item_id=listing_id).delete()
        if not deleted:
            return Response({'detail': 'Favorite not found.'}, status=status.HTTP_404_NOT_FOUND)
        Item.objects.filter(pk=listing_id, favorite_count__gt=0).update(favorite_count=F('favorite_count') - 1)
        return Response(status=status.HTTP_204_NO_CONTENT)


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
