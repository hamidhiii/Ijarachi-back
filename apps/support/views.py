"""
GET  /api/v1/support/            текущая переписка (последнее обращение) или {"ticket": null}
POST /api/v1/support/messages/   {"text", "source": "web"|"owner", "name"?, "phone"?, "page"?}

Вошедший пользователь — по сессии. Гость — по ключу обращения в заголовке
X-Support-Key (его отдаёт первый POST; сайт хранит его у себя). Закрытое
обращение не продолжается: следующее сообщение открывает новое.
"""
from django.db import transaction
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import telegram
from .models import SupportMessage, SupportTicket


class MessageInSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=4000, trim_whitespace=True)
    source = serializers.ChoiceField(choices=[c for c, _ in SupportTicket.SOURCE_CHOICES], default=SupportTicket.SOURCE_WEB)
    name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    page = serializers.CharField(max_length=300, required=False, allow_blank=True)


def _ticket_json(ticket, with_key=False):
    if ticket is None:
        return None
    data = {
        'id': ticket.pk, 'status': ticket.status, 'status_label': ticket.get_status_display(),
        'created_at': ticket.created_at.isoformat(),
        'messages': [{
            'id': m.pk, 'text': m.text, 'from_staff': m.from_staff,
            'staff_name': m.staff_name if m.from_staff else '', 'at': m.created_at.isoformat(),
        } for m in ticket.messages.all()],
    }
    if with_key:
        data['key'] = ticket.access_key
    return data


def _current(request, open_only=False):
    qs = SupportTicket.objects.prefetch_related('messages')
    if request.user and request.user.is_authenticated:
        qs = qs.filter(user=request.user)
    else:
        key = request.headers.get('X-Support-Key', '').strip()
        if not key:
            return None
        qs = qs.filter(access_key=key, user__isnull=True)
    if open_only:
        qs = qs.exclude(status=SupportTicket.STATUS_CLOSED)
    return qs.order_by('-updated_at').first()


class SupportView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        ticket = _current(request)
        if ticket is not None:
            ticket.messages.filter(from_staff=True, read_by_user=False).update(read_by_user=True)
        return Response({'ticket': _ticket_json(ticket), 'available': bool(telegram.agent_chat_ids())})


class SupportMessageView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'support'

    def post(self, request):
        data = MessageInSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        user = request.user if request.user and request.user.is_authenticated else None
        if user is None and not values.get('phone', '').strip():
            return Response({'code': 'SUPPORT_PHONE_REQUIRED', 'detail': 'Оставьте номер, чтобы мы могли ответить.'},
                            status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            ticket = _current(request, open_only=True)
            first = ticket is None
            if first:
                ticket = SupportTicket.objects.create(
                    user=user, name=values.get('name', '').strip(), phone=values.get('phone', '').strip(),
                    source=values['source'], page=values.get('page', '').strip()[:300],
                )
            message = SupportMessage.objects.create(ticket=ticket, text=values['text'])
            ticket.status = SupportTicket.STATUS_OPEN
            ticket.save(update_fields=['status', 'updated_at'])
            telegram.notify_agents(message, first=first)
        ticket = SupportTicket.objects.prefetch_related('messages').get(pk=ticket.pk)
        return Response({'ticket': _ticket_json(ticket, with_key=user is None)}, status=status.HTTP_201_CREATED)
