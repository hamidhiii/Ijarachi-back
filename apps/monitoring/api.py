from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import events
from .models import AuthEvent


class TrackView(APIView):
    """
    POST /api/v1/analytics/track/ — фронт сообщает о шагах до входа:
    {visitor_id, event: visit|auth_opened|phone_entered|client_error, detail?, phone?}.
    Без авторизации: до входа токена ещё нет, а просроченный токен не должен давать 401.
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = 'analytics'

    def post(self, request):
        event = request.data.get('event')
        if event not in AuthEvent.CLIENT_EVENTS:
            return Response({'detail': 'Неизвестное событие.'}, status=400)
        events.record(request, event, phone=str(request.data.get('phone') or ''),
                      detail=request.data.get('detail') or '')
        return Response(status=204)


class PingView(APIView):
    """
    POST /api/v1/analytics/ping/ {visitor_id, source: web|owner|tma} — «я на сайте».
    Фронт шлёт раз в минуту, пока вкладка видима. Токен — по желанию: с ним
    посетитель считается вошедшим (DAU/WAU/MAU). Просроченный или битый токен
    не даёт 401 — просто гость. Без троттлинга по IP: за одним IP мобильного
    оператора сидят тысячи людей, а запись — пара команд Redis.
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        from . import presence

        visitor = str(request.data.get('visitor_id') or '')
        if not presence.valid_visitor(visitor):
            return Response({'detail': 'visitor_id'}, status=400)
        user_id = _user_id(request)
        if presence.ping(visitor, str(request.data.get('source') or 'web'), user_id):
            # Первый заход за день — шаг «Зашёл на сайт» в воронке входа.
            events.record(request, AuthEvent.VISIT, detail=str(request.data.get('source') or '')[:20])
        return Response(status=204)


def _user_id(request):
    from rest_framework_simplejwt.authentication import JWTAuthentication

    try:
        found = JWTAuthentication().authenticate(request)
    except Exception:  # noqa: BLE001 — гость, а не ошибка
        return None
    return found[0].pk if found else None
