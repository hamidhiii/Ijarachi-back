from django.urls import path
from apps.users.views.profile import ProfileView, PublicUserListingsView, PublicUserView
from apps.users.views.auth import (
    KYCUploadView,
    MyIDCallbackView,
    MyIDStartView,
    VerificationStatusView,
)

urlpatterns = [
    path('profile/', ProfileView.as_view(), name='user-profile'),
    path('users/<int:pk>/', PublicUserView.as_view(), name='public-user-detail'),
    path('users/<int:pk>/listings/', PublicUserListingsView.as_view(), name='public-user-listings'),
    path('users/me/verification/', VerificationStatusView.as_view(), name='user-verification-status'),
    path('myid/start/', MyIDStartView.as_view(), name='myid-start'),
    path('myid/callback/', MyIDCallbackView.as_view(), name='myid-callback'),
    path('kyc/upload/', KYCUploadView.as_view(), name='kyc-upload'),
]
