from django.urls import path
from apps.users.views.profile import ProfileView
from apps.users.views.auth import KYCUploadView

urlpatterns = [
    path('profile/', ProfileView.as_view(), name='user-profile'),
    path('kyc/upload/', KYCUploadView.as_view(), name='kyc-upload'),
]
