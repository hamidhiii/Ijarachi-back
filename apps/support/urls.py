from django.urls import path

from .views import SupportMessageView, SupportView

urlpatterns = [
    path('', SupportView.as_view(), name='support'),
    path('messages/', SupportMessageView.as_view(), name='support-messages'),
]
