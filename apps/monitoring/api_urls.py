from django.urls import path

from rest_framework_simplejwt.views import TokenRefreshView

from . import api_monitor as api
from . import panel

urlpatterns = [
    path('login/', api.LoginView.as_view(), name='monitor-api-login'),
    path('refresh/', TokenRefreshView.as_view(), name='monitor-api-refresh'),
    path('me/', api.MeView.as_view(), name='monitor-api-me'),
    path('live/', api.LiveView.as_view(), name='monitor-api-live'),
    path('overview/', api.OverviewView.as_view(), name='monitor-api-overview'),
    path('checks/', api.ChecksView.as_view(), name='monitor-api-checks'),
    path('funnel/', api.FunnelView.as_view(), name='monitor-api-funnel'),

    path('users/', api.UsersView.as_view(), name='monitor-api-users'),
    path('users/<int:pk>/', panel.UserDetailView.as_view(), name='panel-user'),
    path('users/<int:pk>/block/', panel.UserBlockView.as_view(), name='panel-user-block'),
    path('users/<int:pk>/plan/', panel.UserPlanView.as_view(), name='panel-user-plan'),

    path('listings/', api.ListingsView.as_view(), name='monitor-api-listings'),
    path('listings/<int:pk>/', panel.ListingDetailView.as_view(), name='panel-listing'),
    path('listings/<int:pk>/moderate/', panel.ListingModerateView.as_view(), name='panel-listing-moderate'),
    path('listings/<int:pk>/promotion/', panel.ListingPromotionView.as_view(), name='panel-listing-promotion'),
    path('reports/', panel.ReportsView.as_view(), name='panel-reports'),
    path('reports/<int:pk>/resolve/', panel.ReportResolveView.as_view(), name='panel-report-resolve'),

    path('plans/', panel.PlansView.as_view(), name='panel-plans'),
    path('plans/<int:pk>/', panel.PlanDetailView.as_view(), name='panel-plan'),
    path('orders/', api.OrdersView.as_view(), name='monitor-api-orders'),
    path('orders/<int:pk>/action/', panel.OrderActionView.as_view(), name='panel-order-action'),

    path('deals/', api.DealsView.as_view(), name='monitor-api-deals'),
    path('deals/<int:pk>/', panel.DealDetailView.as_view(), name='panel-deal'),
    path('deals/<int:pk>/resolve/', panel.DealResolveView.as_view(), name='panel-deal-resolve'),

    path('kyc/', panel.KycListView.as_view(), name='panel-kyc'),
    path('kyc/<int:pk>/', panel.KycDecisionView.as_view(), name='panel-kyc-decision'),
    path('kyc/<int:pk>/image/<str:side>/', panel.KycImageView.as_view(), name='panel-kyc-image'),

    path('support/', panel.SupportListView.as_view(), name='panel-support'),
    path('support/<int:pk>/', panel.SupportDetailView.as_view(), name='panel-support-ticket'),
    path('support/<int:pk>/reply/', panel.SupportReplyView.as_view(), name='panel-support-reply'),
    path('support/<int:pk>/status/', panel.SupportStatusView.as_view(), name='panel-support-status'),

    path('staff/', panel.StaffView.as_view(), name='panel-staff'),
    path('staff/<int:pk>/', panel.StaffDetailView.as_view(), name='panel-staff-detail'),
    path('audit/', panel.AuditView.as_view(), name='panel-audit'),
]
