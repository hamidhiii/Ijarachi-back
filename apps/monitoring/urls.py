from django.urls import path

from . import views

app_name = 'monitor'

urlpatterns = [
    path('login/', views.MonitorLoginView.as_view(), name='login'),
    path('logout/', views.monitor_logout, name='logout'),

    path('', views.index, name='index'),
    path('deals/', views.deals, name='deals'),
    path('deals/<int:pk>/', views.deal_detail, name='deal_detail'),
    path('stuck/', views.stuck, name='stuck'),
    path('disputes/', views.disputes, name='disputes'),
    path('kyc/', views.kyc, name='kyc'),
    path('payments/', views.payments, name='payments'),
    path('errors/', views.errors, name='errors'),

    path('access/', views.access_list, name='access_list'),
    path('access/new/', views.access_create, name='access_create'),
    path('access/<int:pk>/', views.access_edit, name='access_edit'),
]
