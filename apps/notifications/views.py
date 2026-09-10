from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.schema import DetailSerializer
from .models import Notification, PushSubscription
from .serializers import NotificationSerializer, PushSubscriptionSerializer, PushUnsubscribeSerializer


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        updated = Notification.objects.filter(pk=pk, user=request.user).update(is_read=True)
        if not updated:
            return Response({'detail': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'detail': 'Notification marked as read.'})


class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'detail': 'All notifications marked as read.', 'updated': updated})


@extend_schema_view(
    post=extend_schema(
        request=PushSubscriptionSerializer,
        responses={201: DetailSerializer, 400: DetailSerializer},
        summary='Подписаться на Web Push',
        description=(
            'Тело — объект подписки ровно в том виде, как его отдаёт браузер из '
            'PushManager.subscribe(): {"endpoint","keys":{"p256dh","auth"}}. '
            'Идемпотентно по endpoint — повторный вызов с тем же endpoint просто '
            'обновляет привязку к текущему пользователю.'
        ),
    ),
    delete=extend_schema(
        request=PushUnsubscribeSerializer,
        responses={200: DetailSerializer, 404: DetailSerializer},
        summary='Отписаться от Web Push',
        description='Тело: {"endpoint"}. Удаляет ровно эту подписку (не все подписки пользователя).',
    ),
)
class PushSubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PushSubscriptionSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Подписка сохранена.'}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        serializer = PushUnsubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deleted, _ = PushSubscription.objects.filter(
            endpoint=serializer.validated_data['endpoint'], user=request.user,
        ).delete()
        if not deleted:
            return Response({'detail': 'Подписка не найдена.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'detail': 'Подписка удалена.'})
