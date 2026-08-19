from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from .views import AdminDashboardView, AdminFinanceExportView

urlpatterns = [
    path('admin/', admin.site.urls),

    # API v1
    path('api/v1/auth/', include('apps.users.urls.auth')),
    path('api/v1/telegram/', include('apps.users.urls.telegram')),
    path('api/v1/', include('apps.users.urls.profile')),
    path('api/v1/', include('apps.catalog.urls')),
    path('api/v1/', include('apps.bookings.urls')),
    path('api/v1/', include('apps.chat.urls')),
    path('api/v1/', include('apps.notifications.urls')),
    path('api/v1/payments/', include('apps.payments.urls')),
    path('api/v1/admin-api/dashboard/', AdminDashboardView.as_view(), name='admin-dashboard'),
    path('api/v1/admin-api/finance/export/', AdminFinanceExportView.as_view(), name='admin-finance-export'),

    # Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
