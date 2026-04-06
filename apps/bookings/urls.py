from django.urls import path
from .views import (
    BookingCreateView,
    MyRentalsView,
    BookingDetailView,
    BookingStatusUpdateView,
    PhotoProtocolUploadView,
)

urlpatterns = [
    path('bookings/create/', BookingCreateView.as_view(), name='booking-create'),
    path('bookings/<int:pk>/', BookingDetailView.as_view(), name='booking-detail'),
    path('bookings/<int:pk>/status/', BookingStatusUpdateView.as_view(), name='booking-status'),
    path('bookings/<int:pk>/photos/', PhotoProtocolUploadView.as_view(), name='booking-photos'),
    path('my-rentals/', MyRentalsView.as_view(), name='my-rentals'),
]
