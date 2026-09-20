from django.conf import settings
from django.urls import path
from apps.users.views.profile import ProfileView, PublicUserListingsView, PublicUserView
from apps.users.views.auth import VerificationStatusView

urlpatterns = [
    path('profile/', ProfileView.as_view(), name='user-profile'),
    path('users/<int:pk>/', PublicUserView.as_view(), name='public-user-detail'),
    path('users/<int:pk>/listings/', PublicUserListingsView.as_view(), name='public-user-listings'),
    path('users/me/verification/', VerificationStatusView.as_view(), name='user-verification-status'),
]

# KYC выключен (см. KYC_ENABLED): эндпоинты не регистрируем, а не отвечаем на них
# ошибкой, — и тяжёлые зависимости распознавания (opencv/dlib) не импортируются.
if settings.KYC_ENABLED:
    from apps.users.views.auth import KYCUploadView
    from apps.users.views.kyc import PassportUploadView, PassportConfirmView, FaceVerifyView

    urlpatterns += [
        path('kyc/upload/', KYCUploadView.as_view(), name='kyc-upload'),
        path('kyc/passport/upload/', PassportUploadView.as_view(), name='kyc-passport-upload'),
        path('kyc/passport/confirm/', PassportConfirmView.as_view(), name='kyc-passport-confirm'),
        path('kyc/face/verify/', FaceVerifyView.as_view(), name='kyc-face-verify'),
    ]
