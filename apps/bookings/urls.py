from django.urls import path
from .views import (
    BookingCreateView,
    MyRentalsView,
    BookingDetailView,
    BookingStatusUpdateView,
    AssignDelivererView,
    ConfirmReturnView,
    DealCalculateDeliveryView,
    DealCreateView,
    DealDetailView,
    DealPayView,
    DisputeView,
    MyDealsView,
)

urlpatterns = [
    path('deals/', DealCreateView.as_view(), name='deal-create'),
    path('deals/list/', MyDealsView.as_view(), name='deal-list'),
    path('deals/<int:pk>/', DealDetailView.as_view(), name='deal-detail'),
    path('deals/<int:pk>/calculate-delivery/', DealCalculateDeliveryView.as_view(), name='deal-calculate-delivery'),
    path('deals/<int:pk>/pay/', DealPayView.as_view(), name='deal-pay'),
    path('deals/<int:pk>/confirm-return/', ConfirmReturnView.as_view(), name='deal-confirm-return'),
    path('deals/<int:pk>/dispute/', DisputeView.as_view(), name='deal-dispute'),
    path('deals/<int:pk>/status/', BookingStatusUpdateView.as_view(), name='deal-status'),

    path('bookings/create/', BookingCreateView.as_view(), name='booking-create'),
    path('bookings/<int:pk>/', BookingDetailView.as_view(), name='booking-detail'),
    path('bookings/<int:pk>/status/', BookingStatusUpdateView.as_view(), name='booking-status'),
    path('bookings/<int:pk>/assign-deliverer/', AssignDelivererView.as_view(), name='booking-assign-deliverer'),
    path('my-rentals/', MyRentalsView.as_view(), name='my-rentals'),
]
