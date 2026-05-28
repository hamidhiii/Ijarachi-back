from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import Booking
from .models import DeliveryOrder
from .serializers import DeliveryCalculateSerializer, DeliveryWebhookSerializer
from .services import calculate_delivery_quote


class DeliveryCalculateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeliveryCalculateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(calculate_delivery_quote(**serializer.validated_data))


class DeliveryWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = DeliveryWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order = None
        if data.get('yandex_order_id'):
            order = DeliveryOrder.objects.filter(yandex_order_id=data['yandex_order_id']).select_related('booking').first()
        if not order and data.get('deal_id'):
            order = DeliveryOrder.objects.filter(booking_id=data['deal_id']).select_related('booking').first()
        if not order:
            return Response({'detail': 'Delivery order not found.'}, status=status.HTTP_404_NOT_FOUND)

        order.status = data['status']
        order.raw_payload = data.get('payload', request.data)
        order.save(update_fields=['status', 'raw_payload', 'updated_at'])

        booking = order.booking
        booking.yandex_delivery_order_id = order.yandex_order_id
        booking.yandex_delivery_status = order.status
        if order.status in ['delivered', 'completed']:
            booking.status = Booking.STATUS_IN_PROGRESS
        booking.save(update_fields=['yandex_delivery_order_id', 'yandex_delivery_status', 'status', 'updated_at'])

        try:
            from apps.notifications.tasks import create_notification
            create_notification(booking.renter, 'delivery', {'deal_id': booking.pk, 'status': order.status})
            create_notification(booking.item.owner, 'delivery', {'deal_id': booking.pk, 'status': order.status})
        except Exception:
            pass

        return Response({'detail': 'Delivery status updated.'})
