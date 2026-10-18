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
