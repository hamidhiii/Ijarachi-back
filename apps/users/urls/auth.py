from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from apps.users.views.auth import SendOTPView, VerifyOTPView, LogoutView, KYCUploadView

urlpatterns = [
    path('send-otp/', SendOTPView.as_view(), name='auth-send-otp'),
    path('verify-otp/', VerifyOTPView.as_view(), name='auth-verify-otp'),
    path('refresh/', TokenRefreshView.as_view(), name='auth-token-refresh'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
]
