from django.urls import path

from .moderation import (
    ListingHideView,
    ListingReportView,
    ModerationQueueView,
    ReportListView,
    ReportResolveView,
)
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
    ListingPhoneView,
    ListingReviewsView,
    ListingStatsView,
    MyListingsStatsView,
    MyItemsView,
    ItemUpdateView,
    ItemImageUploadView,
    OfferListCreateView,
    OfferRespondView,
)

urlpatterns = [
    # Rentoo API contract
    path('listings/', ListingListCreateView.as_view(), name='listing-list-create'),
    path('listings/my/stats/', MyListingsStatsView.as_view(), name='my-listings-stats'),
    path('listings/<int:pk>/', ListingDetailUpdateDestroyView.as_view(), name='listing-detail'),
    path('listings/<int:pk>/availability/', ListingAvailabilityView.as_view(), name='listing-availability'),
    path('listings/<int:pk>/reviews/', ListingReviewsView.as_view(), name='listing-reviews'),
    path('listings/<int:pk>/phone/', ListingPhoneView.as_view(), name='listing-phone'),
    path('listings/<int:pk>/report/', ListingReportView.as_view(), name='listing-report'),
    path('admin-api/moderation/queue/', ModerationQueueView.as_view(), name='moderation-queue'),
    path('admin-api/moderation/reports/', ReportListView.as_view(), name='moderation-reports'),
    path('admin-api/moderation/reports/<int:pk>/resolve/', ReportResolveView.as_view(), name='moderation-report-resolve'),
    path('admin-api/moderation/listings/<int:pk>/hide/', ListingHideView.as_view(), name='moderation-listing-hide'),
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
    path('offers/', OfferListCreateView.as_view(), name='offer-list-create'),
    path('offers/<int:pk>/respond/', OfferRespondView.as_view(), name='offer-respond'),
]
