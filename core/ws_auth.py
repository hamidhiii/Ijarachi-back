from urllib.parse import parse_qs

from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _get_user_from_token(token):
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.tokens import AccessToken
    from rest_framework_simplejwt.exceptions import TokenError

    User = get_user_model()
    try:
        access = AccessToken(token)
        return User.objects.get(pk=access['user_id'])
    except (TokenError, User.DoesNotExist, KeyError):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        token = parse_qs(query_string).get('token', [None])[0]
        scope['user'] = await _get_user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)
