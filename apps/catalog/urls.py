from django.urls import path
from .views import (
    CategoryListView,
    FavoriteDeleteView,
    FavoriteListCreateView,
    ItemListView,
    ItemDetailView,
    ItemCreateView,
    ListingDetailUpdateDestroyView,
    ListingAvailabilityView,
    ListingListCreateView,
    ListingModerationView,
    ListingReviewsView,
    ListingStatsView,
    MyItemsView,
    ItemUpdateView,
    ItemImageUploadView,
)

urlpatterns = [
    # Rentoo API contract
    path('listings/', ListingListCreateView.as_view(), name='listing-list-create'),
    path('listings/<int:pk>/', ListingDetailUpdateDestroyView.as_view(), name='listing-detail'),
    path('listings/<int:pk>/availability/', ListingAvailabilityView.as_view(), name='listing-availability'),
    path('listings/<int:pk>/reviews/', ListingReviewsView.as_view(), name='listing-reviews'),
    path('listings/<int:pk>/stats/', ListingStatsView.as_view(), name='listing-stats'),
    path('listings/<int:pk>/moderate/', ListingModerationView.as_view(), name='listing-moderate'),
    path('listings/<int:item_id>/photos/', ItemImageUploadView.as_view(), name='listing-photo-upload'),
    path('listings/<int:item_id>/photos/<int:image_id>/', ItemImageUploadView.as_view(), name='listing-photo-delete'),
    path('favorites/', FavoriteListCreateView.as_view(), name='favorite-list-create'),
    path('favorites/<int:listing_id>/', FavoriteDeleteView.as_view(), name='favorite-delete'),

    # Public
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('catalog/', ItemListView.as_view(), name='item-list'),
    path('catalog/<int:pk>/', ItemDetailView.as_view(), name='item-detail'),

    # Private
    path('items/create/', ItemCreateView.as_view(), name='item-create'),
    path('items/my/', MyItemsView.as_view(), name='item-my-list'),
    path('items/<int:pk>/', ItemUpdateView.as_view(), name='item-update'),
    path('items/<int:item_id>/images/', ItemImageUploadView.as_view(), name='item-image-upload'),
    path('items/<int:item_id>/images/<int:image_id>/', ItemImageUploadView.as_view(), name='item-image-delete'),
]
