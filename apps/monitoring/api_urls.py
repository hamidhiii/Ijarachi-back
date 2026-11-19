from django.urls import path

from . import api_monitor as api

urlpatterns = [
    path('login/', api.LoginView.as_view(), name='monitor-api-login'),
    path('me/', api.MeView.as_view(), name='monitor-api-me'),
    path('live/', api.LiveView.as_view(), name='monitor-api-live'),
    path('overview/', api.OverviewView.as_view(), name='monitor-api-overview'),
    path('checks/', api.ChecksView.as_view(), name='monitor-api-checks'),
    path('funnel/', api.FunnelView.as_view(), name='monitor-api-funnel'),
    path('users/', api.UsersView.as_view(), name='monitor-api-users'),
    path('listings/', api.ListingsView.as_view(), name='monitor-api-listings'),
    path('deals/', api.DealsView.as_view(), name='monitor-api-deals'),
    path('orders/', api.OrdersView.as_view(), name='monitor-api-orders'),
]
