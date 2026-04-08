from django.urls import path
from .views import (
    BookingCreateView,
    MyRentalsView,
    BookingDetailView,
    BookingStatusUpdateView,
    VerificationPhotoUploadView,
    ComparePhotosAIView,
)

app_name = 'bookings'

urlpatterns = [
    path('create/', BookingCreateView.as_view(), name='create'),
    path('my/', MyRentalsView.as_view(), name='my-rentals'),
    path('<int:pk>/', BookingDetailView.as_view(), name='detail'),
    path('<int:pk>/status/', BookingStatusUpdateView.as_view(), name='status-update'),
    path('<int:pk>/verification-photos/', VerificationPhotoUploadView.as_view(), name='verification-photos'),
    path('ai-compare/', ComparePhotosAIView.as_view(), name='ai-compare'),
]
