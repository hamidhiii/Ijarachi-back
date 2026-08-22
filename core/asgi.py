import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

django_asgi_app = get_asgi_application()

from core.ws_auth import JWTAuthMiddleware
from apps.chat.routing import websocket_urlpatterns as chat_websocket_urlpatterns
from apps.notifications.routing import websocket_urlpatterns as notifications_websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': JWTAuthMiddleware(
        URLRouter(chat_websocket_urlpatterns + notifications_websocket_urlpatterns)
    ),
})
