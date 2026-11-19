from django.urls import path

from .bot_views import CrmBotLinkView
from .views import (
    AccountsView,
    BranchDetailView,
    BranchListCreateView,
    ClientDetailView,
    ClientListCreateView,
    ExportView,
    ListingCalendarView,
    OwnerListingDetailView,
    OwnerListingPublishView,
    OwnerListingsView,
    ReservationDetailView,
    ReservationListCreateView,
    StaffDetailView,
    StaffListCreateView,
    StatsView,
    StockView,
)

urlpatterns = [
    path('accounts/', AccountsView.as_view(), name='owner-accounts'),
    path('staff/', StaffListCreateView.as_view(), name='owner-staff'),
    path('staff/<int:pk>/', StaffDetailView.as_view(), name='owner-staff-detail'),
    path('branches/', BranchListCreateView.as_view(), name='owner-branches'),
    path('branches/<int:pk>/', BranchDetailView.as_view(), name='owner-branch-detail'),
    path('listings/', OwnerListingsView.as_view(), name='owner-listings'),
    path('listings/<int:pk>/', OwnerListingDetailView.as_view(), name='owner-listing-detail'),
    path('listings/<int:pk>/publish/', OwnerListingPublishView.as_view(), name='owner-listing-publish'),
    path('listings/<int:pk>/calendar/', ListingCalendarView.as_view(), name='owner-listing-calendar'),
    path('stock/', StockView.as_view(), name='owner-stock'),
    path('reservations/', ReservationListCreateView.as_view(), name='owner-reservations'),
    path('reservations/<int:pk>/', ReservationDetailView.as_view(), name='owner-reservation-detail'),
    path('clients/', ClientListCreateView.as_view(), name='owner-clients'),
    path('clients/<int:pk>/', ClientDetailView.as_view(), name='owner-client-detail'),
    path('stats/', StatsView.as_view(), name='owner-stats'),
    path('export/<str:entity>/', ExportView.as_view(), name='owner-export'),
    path('telegram/', CrmBotLinkView.as_view(), name='owner-telegram'),
]
