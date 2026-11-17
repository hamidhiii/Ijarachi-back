"""
Жалобы на объявления и очередь модерации (решение 16.11.2026).

Пользователь жалуется: POST /listings/{id}/report/. Сотрудник (is_staff) видит
очередь — объявления на модерации и объявления с открытыми жалобами — и решает:
одобрить/отклонить (как раньше, /listings/{id}/moderate/), скрыть или вернуть
скрытое, отклонить жалобу. Скрытое (`blocked`) не видно в каталоге, не
считается в лимите, и владелец сам его не вернёт.
"""
from django.db import transaction
from django.db.models import Count, Min, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Item, Report


class ReportCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ['id', 'reason', 'comment', 'status', 'created_at']
        read_only_fields = ['id', 'status', 'created_at']


class ReportSerializer(serializers.ModelSerializer):
    listing = serializers.IntegerField(source='item_id', read_only=True)
    listing_title = serializers.CharField(source='item.title', read_only=True)
    listing_status = serializers.CharField(source='item.status', read_only=True)
    reporter_phone = serializers.CharField(source='reporter.phone', read_only=True, default=None)

    class Meta:
        model = Report
        fields = [
            'id', 'listing', 'listing_title', 'listing_status', 'reporter_phone',
            'reason', 'comment', 'status', 'resolution', 'resolved_by', 'resolved_at', 'created_at',
        ]


class QueueRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    status = serializers.CharField()
    owner_id = serializers.IntegerField()
    owner_phone = serializers.CharField()
    open_reports = serializers.IntegerField()
    waiting_since = serializers.DateTimeField()


class ReportResolveSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['dismiss', 'hide'])
    comment = serializers.CharField(required=False, allow_blank=True, max_length=500)


class HideSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class ListingReportView(APIView):
    """
    POST /api/v1/listings/{id}/report/ {"reason": "...", "comment": ""} — жалоба.
    Одна открытая жалоба пользователя на объявление: повтор — 200 с той же жалобой.
    На своё объявление — 400 `own_listing`.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'report'

    @extend_schema(request=ReportCreateSerializer, responses={201: ReportCreateSerializer, 200: ReportCreateSerializer})
    def post(self, request, pk):
        item = Item.objects.filter(pk=pk, status=Item.STATUS_APPROVED).first()
        if item is None:
            raise NotFound('Объявление не найдено.')
        if item.owner_id == request.user.pk:
            return Response(
                {'code': 'own_listing', 'detail': 'Нельзя пожаловаться на своё объявление.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = ReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            existing = Report.objects.select_for_update().filter(
                item=item, reporter=request.user, status=Report.STATUS_NEW,
            ).first()
            if existing:
                return Response(ReportCreateSerializer(existing).data)
            report = serializer.save(item=item, reporter=request.user)
        return Response(ReportCreateSerializer(report).data, status=status.HTTP_201_CREATED)


class ModerationQueueView(generics.ListAPIView):
    """
    GET /api/v1/admin-api/moderation/queue/ — что ждёт сотрудника: объявления на
    модерации и объявления с открытыми жалобами. Сначала с жалобами (больше —
    выше), потом по времени ожидания.
    """
    permission_classes = [permissions.IsAdminUser]
    serializer_class = QueueRowSerializer

    def get_queryset(self):
        return (
            Item.objects
            .annotate(
                open_reports=Count('reports', filter=Q(reports__status=Report.STATUS_NEW)),
                first_report=Min('reports__created_at', filter=Q(reports__status=Report.STATUS_NEW)),
            )
            .filter(Q(status=Item.STATUS_PENDING) | Q(open_reports__gt=0))
            .select_related('owner')
            .order_by('-open_reports', 'updated_at')
        )

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        rows = [
            {
                'id': item.pk, 'title': item.title, 'status': item.status,
                'owner_id': item.owner_id, 'owner_phone': item.owner.phone,
                'open_reports': item.open_reports,
                'waiting_since': item.first_report or item.updated_at,
            }
            for item in page
        ]
        return self.get_paginated_response(QueueRowSerializer(rows, many=True).data)


class ReportListView(generics.ListAPIView):
    """GET /api/v1/admin-api/moderation/reports/?status=new&listing= — жалобы."""
    permission_classes = [permissions.IsAdminUser]
    serializer_class = ReportSerializer

    def get_queryset(self):
        qs = Report.objects.select_related('item', 'reporter')
        params = self.request.query_params
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('listing'):
            qs = qs.filter(item_id=params['listing'])
        return qs


def _notify_owner(item, title, message):
    from apps.notifications.models import Notification
    from apps.notifications.tasks import create_notification

    transaction.on_commit(lambda: create_notification(item.owner, Notification.TYPE_SYSTEM, {
        'title': title, 'message': message, 'listing_id': item.pk,
    }))


def hide_listing(item, staff, reason):
    """Скрыть объявление и закрыть все открытые жалобы на него."""
    item.status = Item.STATUS_BLOCKED
    item.rejection_reason = reason
    item.save(update_fields=['status', 'rejection_reason', 'updated_at'])
    Report.objects.filter(item=item, status=Report.STATUS_NEW).update(
        status=Report.STATUS_ACTION_TAKEN, resolved_by=staff, resolved_at=timezone.now(), resolution=reason,
    )
    _notify_owner(item, 'Объявление скрыто', f'«{item.title}» скрыто модератором. Причина: {reason}')


class ReportResolveView(APIView):
    """
    POST /api/v1/admin-api/moderation/reports/{id}/resolve/
    {"action": "dismiss" | "hide", "comment": ""} — отклонить жалобу или скрыть
    объявление (тогда закрываются все открытые жалобы на него).
    """
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(request=ReportResolveSerializer, responses=ReportSerializer)
    def post(self, request, pk):
        serializer = ReportResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.validated_data.get('comment', '')
        with transaction.atomic():
            report = Report.objects.select_for_update().select_related('item__owner').filter(pk=pk).first()
            if report is None:
                raise NotFound('Жалоба не найдена.')
            if serializer.validated_data['action'] == 'hide':
                hide_listing(report.item, request.user, comment or report.get_reason_display())
            elif report.status == Report.STATUS_NEW:
                report.status = Report.STATUS_DISMISSED
                report.resolved_by = request.user
                report.resolved_at = timezone.now()
                report.resolution = comment
                report.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution'])
        report.refresh_from_db()
        return Response(ReportSerializer(report).data)


class ListingHideView(APIView):
    """
    POST   /api/v1/admin-api/moderation/listings/{id}/hide/ {"reason": "..."} — скрыть.
    DELETE /api/v1/admin-api/moderation/listings/{id}/hide/ — вернуть в публикацию.
    """
    permission_classes = [permissions.IsAdminUser]

    @extend_schema(request=HideSerializer, responses={200: None})
    def post(self, request, pk):
        serializer = HideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            item = Item.objects.select_for_update().select_related('owner').filter(pk=pk).first()
            if item is None:
                raise NotFound('Объявление не найдено.')
            hide_listing(item, request.user, serializer.validated_data['reason'])
        return Response({'id': item.pk, 'status': item.status})

    @extend_schema(request=None, responses={200: None})
    def delete(self, request, pk):
        with transaction.atomic():
            item = Item.objects.select_for_update().select_related('owner').filter(pk=pk).first()
            if item is None:
                raise NotFound('Объявление не найдено.')
            if item.status == Item.STATUS_BLOCKED:
                item.status = Item.STATUS_APPROVED
                item.rejection_reason = ''
                item.save(update_fields=['status', 'rejection_reason', 'updated_at'])
                _notify_owner(item, 'Объявление снова опубликовано', f'«{item.title}» снова видно в каталоге.')
        return Response({'id': item.pk, 'status': item.status})
