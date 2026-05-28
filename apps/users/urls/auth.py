from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from apps.users.views.auth import (
    LoginView,
    LogoutView,
    PhoneChangeSendView,
    PhoneChangeVerifyView,
    RegisterView,
    SendOTPView,
    VerifyOTPView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='auth-register'),
    path('login/', LoginView.as_view(), name='auth-login'),
    path('sms/send/', SendOTPView.as_view(), name='auth-sms-send'),
    path('sms/verify/', VerifyOTPView.as_view(), name='auth-sms-verify'),
    path('send-otp/', SendOTPView.as_view(), name='auth-send-otp'),
    path('verify-otp/', VerifyOTPView.as_view(), name='auth-verify-otp'),
    path('refresh/', TokenRefreshView.as_view(), name='auth-token-refresh'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
    path('phone/change/send/', PhoneChangeSendView.as_view(), name='auth-phone-change-send'),
    path('phone/change/verify/', PhoneChangeVerifyView.as_view(), name='auth-phone-change-verify'),
]
