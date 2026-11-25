"""
Действия админ-панели (back.rentoo.uz/admin). Каждое — через те же сервисы,
что и сайт и Django-админка, и с записью в журнал (AuditLog, action `panel.*`).

    GET  users/<id>/                       карточка пользователя
    POST users/<id>/block/  {blocked}      заблокировать / разблокировать     [users: edit]
    POST users/<id>/plan/   {plan, days, amount?, comment?, notify?}         [billing: edit]
    GET  listings/<id>/                    карточка объявления с фото и жалобами
    POST listings/<id>/moderate/ {action: approve|reject|hide|restore, reason?} [listings: edit]
    POST listings/<id>/promotion/ {kind, days} | {stop: top|vip|all}       [billing: edit]
    GET  reports/?status=                  жалобы
    POST reports/<id>/resolve/ {action: dismiss|hide, comment?}           [listings: edit]
    GET  plans/  PATCH plans/<id>/         тарифы: цены, лимиты, права         [billing]
    POST orders/<id>/action/ {action: mark_paid|cancel|apply|clear}       [payments: edit]
    GET  deals/<id>/  POST deals/<id>/resolve/ {deposit_withheld, comment}  [deals]
    GET  kyc/?status=  GET kyc/<id>/image/<side>/  POST kyc/<id>/ {action, reason} [kyc]
    GET  staff/  POST staff/  PATCH staff/<id>/  DELETE staff/<id>/        [staff]
    GET  audit/                            журнал действий                   [staff: view]
    GET  support/?status=&q=  GET support/<id>/                            [support: view]
    POST support/<id>/reply/ {text}  POST support/<id>/status/ {status: open|closed} [support: edit]
"""
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from .api_monitor import MonitorView, _page, can
from .roles import CUSTOM, ROLES, SECTIONS, normalize, role_for

User = get_user_model()


def audit(request, action, **metadata):
    from apps.notifications.models import AuditLog

    try:
        AuditLog.objects.create(
            user=request.user, action=f'panel.{action}', metadata=metadata,
            ip_address=request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:300],
        )
    except Exception:  # noqa: BLE001 — журнал не должен ломать действие
        pass


def _iso(value):
    return value.isoformat() if value else None


def _url(request, field):
    try:
        return request.build_absolute_uri(field.url) if field else None
    except ValueError:
        return None


# ─── Пользователи ───────────────────────────────────────────────────────────

class UserDetailView(MonitorView):
    section = 'users'

    def get(self, request, pk):
        from apps.billing.models import SubscriptionPeriod
        from apps.billing.plans import current_plan
        from apps.bookings.models import Booking
        from apps.catalog.models import Item

        from . import presence

        user = User.objects.select_related('profile').filter(pk=pk).first()
        if user is None:
            raise NotFound('Пользователь не найден.')
        profile = getattr(user, 'profile', None)
        subscription = getattr(user, 'subscription', None)
        plan = current_plan(user)
        passport = getattr(user, 'passport', None)
        items = Item.objects.filter(owner=user).order_by('-created_at')
        money = can(request, 'payments')
        return Response({
            'id': user.pk, 'phone': user.phone, 'active': user.is_active, 'staff': user.is_staff,
            'superuser': user.is_superuser,
            'name': getattr(profile, 'full_name', '') or '', 'shop': getattr(profile, 'shop_name', '') or '',
            'type': getattr(profile, 'account_type', ''), 'verified': bool(getattr(profile, 'is_verified_kyc', False)),
            'joined': _iso(user.date_joined), 'last_seen': _iso(presence.last_seen([user.pk]).get(user.pk)),
            'plan': {'code': plan.code, 'name': plan.name,
                     'until': _iso(subscription.ends_at) if subscription and subscription.ends_at > timezone.now() else None},
            'plan_history': [
                {'plan': p.plan.name, 'from': _iso(p.starts_at), 'to': _iso(p.ends_at), 'source': p.get_source_display(),
                 'amount': int(p.amount) if money else None, 'by': p.created_by.phone if p.created_by_id else '',
                 'comment': p.comment}
                for p in SubscriptionPeriod.objects.filter(user=user).select_related('plan', 'created_by').order_by('-starts_at')[:20]
            ],
            'kyc': {'status': passport.status, 'status_label': passport.get_status_display(), 'id': passport.pk}
            if passport else None,
            'listings': [
                {'id': i.pk, 'title': i.title, 'status': i.status, 'status_label': i.get_status_display(),
                 'price': int(i.price_per_day), 'at': _iso(i.created_at)}
                for i in items[:30]
            ],
            'listings_total': items.count(),
            'deals_as_renter': Booking.objects.filter(renter=user).exclude(status=Booking.STATUS_DRAFT).count(),
            'deals_as_owner': Booking.objects.filter(item__owner=user).exclude(status=Booking.STATUS_DRAFT).count(),
            'can_edit': can(request, 'users', 'edit'), 'can_plan': can(request, 'billing', 'edit'),
        })


class UserBlockView(MonitorView):
    section = 'users'

    def post(self, request, pk):
        from core.views import revoke_refresh_tokens

        user = User.objects.filter(pk=pk).first()
        if user is None:
            raise NotFound('Пользователь не найден.')
        if user.pk == request.user.pk:
            raise ValidationError({'detail': 'Нельзя заблокировать себя.'})
        if user.is_superuser and not request.monitor_access.is_superuser:
            raise ValidationError({'detail': 'Суперюзера блокирует только суперюзер.'})
        blocked = bool(request.data.get('blocked'))
        user.is_active = not blocked
        user.save(update_fields=['is_active'])
        if blocked:
            revoke_refresh_tokens(user)
        audit(request, 'user.block' if blocked else 'user.unblock', user=user.pk, phone=user.phone)
        return Response({'id': user.pk, 'active': user.is_active})


class UserPlanView(MonitorView):
    section = 'users'
    edit_section = 'billing'

    def post(self, request, pk):
        from apps.billing.admin_actions import apply_plan
        from apps.billing.models import Plan

        user = User.objects.filter(pk=pk).first()
        if user is None:
            raise NotFound('Пользователь не найден.')
        plan = Plan.objects.filter(code=request.data.get('plan')).first()
        if plan is None:
            raise ValidationError({'plan': 'Неизвестный тариф.'})
        try:
            days = int(request.data.get('days') or 30)
            amount = int(Decimal(str(request.data.get('amount') or 0)))
        except (TypeError, ValueError, InvalidOperation):
            raise ValidationError({'detail': 'Срок и сумма — числа.'})
        if not 1 <= days <= 3650 or amount < 0:
            raise ValidationError({'detail': 'Срок 1–3650 дней, сумма не меньше 0.'})
        with transaction.atomic():
            changed = apply_plan(user, plan=plan, days=days, amount=amount, staff=request.user,
                                 comment=str(request.data.get('comment') or 'Выдан в панели')[:200],
                                 notify=bool(request.data.get('notify', True)))
        audit(request, 'user.plan', user=user.pk, plan=plan.code, days=days, amount=amount, changed=bool(changed))
        return Response({'ok': True, 'changed': bool(changed)})


# ─── Объявления, жалобы, продвижение ────────────────────────────────────────

class ListingDetailView(MonitorView):
    section = 'listings'

    def get(self, request, pk):
        from apps.catalog.models import Item, Report

        item = Item.objects.select_related('owner', 'category').prefetch_related('images').filter(pk=pk).first()
        if item is None:
            raise NotFound('Объявление не найдено.')
        now = timezone.now()
        return Response({
            'id': item.pk, 'title': item.title, 'description': item.description, 'status': item.status,
            'status_label': item.get_status_display(), 'rejection_reason': item.rejection_reason,
            'category': item.category.name if item.category_id else '', 'price': int(item.price_per_day),
            'deposit': int(item.deposit), 'quantity': item.quantity, 'city': item.city, 'address': item.address,
            'views': item.view_count, 'favorites': item.favorite_count,
            'owner': {'id': item.owner_id, 'phone': item.owner.phone},
            'photos': [_url(request, image.image) for image in item.images.all() if image.image],
            'top_until': _iso(item.top_until) if item.top_until and item.top_until > now else None,
            'vip_until': _iso(item.vip_until) if item.vip_until and item.vip_until > now else None,
            'reports': [
                {'id': r.id, 'reason': r.get_reason_display(), 'comment': r.comment, 'status': r.status,
                 'status_label': r.get_status_display(), 'at': _iso(r.created_at)}
                for r in Report.objects.filter(item=item).order_by('-created_at')[:20]
            ],
            'created': _iso(item.created_at), 'updated': _iso(item.updated_at),
            'can_edit': can(request, 'listings', 'edit'), 'can_promote': can(request, 'billing', 'edit'),
        })


class ListingModerateView(MonitorView):
    section = 'listings'

    def post(self, request, pk):
        from apps.catalog.models import Item
        from apps.catalog.moderation import _notify_owner, hide_listing

        action = request.data.get('action')
        reason = str(request.data.get('reason') or '').strip()[:500]
        if action not in ('approve', 'reject', 'hide', 'restore'):
            raise ValidationError({'action': 'approve, reject, hide или restore.'})
        if action in ('reject', 'hide') and not reason:
            raise ValidationError({'reason': 'Напишите причину — её увидит владелец.'})
        with transaction.atomic():
            item = Item.objects.select_for_update().select_related('owner').filter(pk=pk).first()
            if item is None:
                raise NotFound('Объявление не найдено.')
            if action == 'hide':
                hide_listing(item, request.user, reason)
            else:
                item.status = {'approve': Item.STATUS_APPROVED, 'reject': Item.STATUS_REJECTED,
                               'restore': Item.STATUS_APPROVED}[action]
                item.rejection_reason = reason if action == 'reject' else ''
                item.save(update_fields=['status', 'rejection_reason', 'updated_at'])
                if action == 'reject':
                    _notify_owner(item, 'Объявление отклонено', f'«{item.title}» отклонено на модерации. Причина: {reason}')
                else:
                    _notify_owner(item, 'Объявление опубликовано', f'«{item.title}» прошло модерацию и опубликовано.')
        audit(request, f'listing.{action}', listing=item.pk, reason=reason)
        return Response({'id': item.pk, 'status': item.status, 'status_label': item.get_status_display()})


class ListingPromotionView(MonitorView):
    section = 'listings'
    edit_section = 'billing'

    def post(self, request, pk):
        from apps.billing.admin_actions import apply_promotion, stop_promotions
        from apps.catalog.models import Item

        item = Item.objects.select_related('owner').filter(pk=pk).first()
        if item is None:
            raise NotFound('Объявление не найдено.')
        stop = request.data.get('stop')
        with transaction.atomic():
            if stop:
                if stop not in ('top', 'vip', 'all'):
                    raise ValidationError({'stop': 'top, vip или all.'})
                stop_promotions(item, stop)
                audit(request, 'listing.promotion_stop', listing=item.pk, kind=stop)
            else:
                kind = request.data.get('kind')
                try:
                    days = int(request.data.get('days') or 7)
                except (TypeError, ValueError):
                    raise ValidationError({'days': 'Число дней.'})
                if kind not in ('top', 'vip') or not 1 <= days <= 365:
                    raise ValidationError({'detail': 'kind: top или vip, срок 1–365 дней.'})
                apply_promotion(item, kind=kind, days=days, notify=bool(request.data.get('notify', True)))
                audit(request, 'listing.promotion', listing=item.pk, kind=kind, days=days)
        return Response({'ok': True})


class ReportsView(MonitorView):
    section = 'listings'

    def get(self, request):
        from apps.catalog.models import Report

        qs = Report.objects.select_related('item', 'reporter').order_by('-created_at')
        status = request.query_params.get('status', 'new')
        if status:
            qs = qs.filter(status=status)
        return _page(request, qs, lambda r: {
            'id': r.pk, 'listing': r.item_id, 'title': r.item.title, 'listing_status': r.item.status,
            'reason': r.get_reason_display(), 'comment': r.comment, 'status': r.status,
            'status_label': r.get_status_display(), 'reporter': r.reporter.phone if r.reporter_id else '',
            'at': _iso(r.created_at),
        })


class ReportResolveView(MonitorView):
    section = 'listings'

    def post(self, request, pk):
        from apps.catalog.models import Report
        from apps.catalog.moderation import hide_listing

        action = request.data.get('action')
        comment = str(request.data.get('comment') or '')[:500]
        if action not in ('dismiss', 'hide'):
            raise ValidationError({'action': 'dismiss или hide.'})
        with transaction.atomic():
            report = Report.objects.select_for_update().select_related('item__owner').filter(pk=pk).first()
            if report is None:
                raise NotFound('Жалоба не найдена.')
            if action == 'hide':
                hide_listing(report.item, request.user, comment or report.get_reason_display())
            elif report.status == Report.STATUS_NEW:
                report.status = Report.STATUS_DISMISSED
                report.resolved_by = request.user
                report.resolved_at = timezone.now()
                report.resolution = comment
                report.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution'])
        audit(request, f'report.{action}', report=pk, listing=report.item_id)
        return Response({'ok': True})


# ─── Тарифы и заказы ────────────────────────────────────────────────────────

PLAN_FIELDS = ('price', 'listing_limit', 'crm', 'search_priority', 'staff_access', 'statistics', 'branches',
               'data_export', 'is_active')


def _plan(plan):
    return {'id': plan.pk, 'code': plan.code, 'name': plan.name, 'price': int(plan.price),
            'listing_limit': plan.listing_limit, 'crm': plan.crm, 'search_priority': plan.search_priority,
            'staff_access': plan.staff_access, 'statistics': plan.statistics, 'branches': plan.branches,
            'data_export': plan.data_export, 'is_active': plan.is_active, 'rank': plan.rank,
            'subscribers': plan.subscriptions.filter(ends_at__gt=timezone.now()).count() if plan.is_paid else None}


class PlansView(MonitorView):
    section = 'billing'

    def get(self, request):
        from apps.billing.models import Plan

        return Response([_plan(p) for p in Plan.objects.order_by('rank')])


class PlanDetailView(MonitorView):
    section = 'billing'

    def patch(self, request, pk):
        from apps.billing.models import Plan

        plan = Plan.objects.filter(pk=pk).first()
        if plan is None:
            raise NotFound('Тариф не найден.')
        changed = {}
        for field in PLAN_FIELDS:
            if field not in request.data:
                continue
            value = request.data[field]
            if field == 'price':
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise ValidationError({'price': 'Число.'})
                if value < 0:
                    raise ValidationError({'price': 'Не меньше 0.'})
            elif field == 'listing_limit':
                value = None if value in (None, '') else int(value)
            else:
                value = bool(value)
            changed[field] = value
            setattr(plan, field, value)
        if changed:
            plan.save(update_fields=list(changed))
            audit(request, 'plan.update', plan=plan.code, **{k: v for k, v in changed.items()})
        return Response(_plan(plan))


class OrderActionView(MonitorView):
    section = 'payments'

    def post(self, request, pk):
        from apps.billing.admin_actions import apply_plan
        from apps.billing.models import BillingOrder
        from apps.billing.services import mark_order_paid, period_days

        action = request.data.get('action')
        order = BillingOrder.objects.select_related('user', 'plan').filter(pk=pk).first()
        if order is None:
            raise NotFound('Заказ не найден.')
        with transaction.atomic():
            if action == 'mark_paid':
                if order.status != BillingOrder.STATUS_PENDING:
                    raise ValidationError({'detail': 'Оплаченным можно отметить только заказ «Ждёт оплаты».'})
                BillingOrder.objects.filter(pk=order.pk).update(raw={
                    **order.raw, 'manual_paid_by': str(request.user), 'manual_paid_at': timezone.now().isoformat()})
                mark_order_paid(order.pk)
            elif action == 'cancel':
                if order.status != BillingOrder.STATUS_PENDING:
                    raise ValidationError({'detail': 'Отменить можно только заказ «Ждёт оплаты».'})
                BillingOrder.objects.filter(pk=order.pk).update(status=BillingOrder.STATUS_CANCELLED)
            elif action == 'apply':
                if order.status != BillingOrder.STATUS_PAID or order.kind != BillingOrder.KIND_PLAN or not order.needs_attention:
                    raise ValidationError({'detail': 'Применить можно оплаченный тариф с пометкой «требует внимания».'})
                apply_plan(order.user, plan=order.plan, days=period_days(), amount=order.amount,
                           comment=f'Заказ #{order.pk}, применён в панели', staff=request.user)
                BillingOrder.objects.filter(pk=order.pk).update(needs_attention='')
            elif action == 'clear':
                BillingOrder.objects.filter(pk=order.pk).update(needs_attention='')
            else:
                raise ValidationError({'action': 'mark_paid, cancel, apply или clear.'})
        audit(request, f'order.{action}', order=order.pk, amount=int(order.amount))
        order.refresh_from_db()
        return Response({'id': order.pk, 'status': order.status, 'attention': order.needs_attention})


# ─── Сделки ─────────────────────────────────────────────────────────────────

class DealDetailView(MonitorView):
    section = 'deals'

    def get(self, request, pk):
        from apps.bookings.models import Booking

        deal = (Booking.objects.select_related('item__owner', 'renter')
                .prefetch_related('deposit_operations', 'photos').filter(pk=pk).first())
        if deal is None:
            raise NotFound('Сделка не найдена.')
        money = can(request, 'payments')
        hide = (lambda v: int(v) if money and v is not None else None)
        return Response({
            'id': deal.pk, 'status': deal.status, 'status_label': deal.get_status_display(),
            'listing': {'id': deal.item_id, 'title': deal.item.title if deal.item_id else '—'},
            'owner': deal.item.owner.phone if deal.item_id else '', 'renter': deal.renter.phone if deal.renter_id else '',
            'from': _iso(deal.start_date), 'to': _iso(deal.end_date),
            'price_per_day': hide(deal.price_per_day), 'total': hide(deal.total_price),
            'deposit': hide(deal.deposit_amount), 'commission': hide(deal.commission_amount),
            'escrow': deal.get_escrow_status_display(), 'deposit_status': deal.deposit_status,
            'dispute_reason': deal.dispute_reason, 'renter_comment': deal.renter_comment,
            'operations': [
                {'type': op.get_type_display(), 'amount': hide(op.amount), 'comment': op.comment,
                 'by': op.actor.phone if op.actor_id else '', 'at': _iso(op.created_at)}
                for op in deal.deposit_operations.all()
            ] if money else [],
            'photos': [{'kind': p.kind, 'url': _url(request, p.image), 'comment': p.comment} for p in deal.photos.all()],
            'created': _iso(deal.created_at),
            'can_resolve': deal.status == Booking.STATUS_DISPUTED and can(request, 'deals', 'edit'),
        })


class DealResolveView(MonitorView):
    section = 'deals'

    def post(self, request, pk):
        from apps.bookings.settlement import SettlementError, resolve_dispute
        from apps.bookings.tasks import notify_status_change

        try:
            withheld = Decimal(str(request.data.get('deposit_withheld') or 0))
        except InvalidOperation:
            raise ValidationError({'deposit_withheld': 'Число.'})
        comment = str(request.data.get('comment') or '')[:500]
        try:
            booking = resolve_dispute(pk, withheld, actor=request.user, comment=comment)
        except SettlementError as exc:
            raise ValidationError({'detail': str(exc)})
        transaction.on_commit(lambda: notify_status_change.delay(booking.pk, request.user.pk))
        audit(request, 'deal.resolve', deal=pk, deposit_withheld=str(withheld))
        return Response({'id': booking.pk, 'status': booking.status})


# ─── KYC ────────────────────────────────────────────────────────────────────

class KycListView(MonitorView):
    section = 'kyc'

    def get(self, request):
        from apps.users.models import PassportDocument

        qs = PassportDocument.objects.select_related('user').order_by('-submitted_at')
        if request.query_params.get('status', 'pending'):
            qs = qs.filter(status=request.query_params.get('status', 'pending'))
        return _page(request, qs, lambda d: {
            'id': d.pk, 'user': d.user_id, 'phone': d.user.phone, 'type': d.get_document_type_display(),
            'full_name': d.full_name, 'series': d.series, 'number': d.number, 'pinfl': d.pinfl,
            'birth_date': _iso(d.birth_date), 'expiry_date': _iso(d.expiry_date),
            'status': d.status, 'status_label': d.get_status_display(), 'reject_reason': d.reject_reason,
            'sides': [side for side in ('front', 'back', 'face') if getattr(d, f'{side}_image')],
            'submitted': _iso(d.submitted_at),
        })


class KycImageView(MonitorView):
    """Фото документа — только через панель с правом kyc (в браузер — blob по токену)."""
    section = 'kyc'

    def get(self, request, pk, side):
        from apps.users.models import PassportDocument

        if side not in ('front', 'back', 'face'):
            raise Http404
        doc = PassportDocument.objects.filter(pk=pk).first()
        image = getattr(doc, f'{side}_image', None) if doc else None
        if not image:
            raise Http404
        audit(request, 'kyc.view_image', document=pk, side=side)
        return FileResponse(image.open('rb'))


class KycDecisionView(MonitorView):
    section = 'kyc'

    def post(self, request, pk):
        from apps.users.models import PassportDocument

        doc = PassportDocument.objects.filter(pk=pk).first()
        if doc is None:
            raise NotFound('Документ не найден.')
        action = request.data.get('action')
        if action == 'approve':
            doc.mark_verified()
        elif action == 'reject':
            reason = str(request.data.get('reason') or '').strip()
            if not reason:
                raise ValidationError({'reason': 'Напишите причину отказа.'})
            doc.mark_rejected(reason[:300])
        else:
            raise ValidationError({'action': 'approve или reject.'})
        audit(request, f'kyc.{action}', document=pk, user=doc.user_id)
        return Response({'id': doc.pk, 'status': doc.status})


# ─── Сотрудники и роли ──────────────────────────────────────────────────────

def _staff_row(access):
    profile = getattr(access.user, 'profile', None)
    return {
        'id': access.pk, 'user': access.user_id, 'phone': access.user.phone,
        'name': getattr(profile, 'full_name', '') or '', 'active': access.is_active and access.user.is_active,
        'role': role_for(access.permissions), 'permissions': normalize(access.permissions), 'note': access.note,
        'created': _iso(access.created_at), 'by': access.created_by.phone if access.created_by_id else '',
        'has_password': access.user.has_usable_password(),
    }


def _permissions_from(data):
    role = data.get('role')
    if role in ROLES and not data.get('permissions'):
        return dict(ROLES[role][1])
    return normalize(data.get('permissions'))


def _set_password(user, password):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError

    # Вход в панель — пароль, а не код: не короче 10 символов, плюс валидаторы Django.
    if len(password) < 10:
        raise ValidationError({'password': ['Пароль не короче 10 символов.']})
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError({'password': list(exc.messages)})
    user.set_password(password)


class StaffView(MonitorView):
    section = 'staff'

    def get(self, request):
        from .models import MonitorAccess

        rows = [_staff_row(a) for a in MonitorAccess.objects.select_related('user__profile', 'created_by')]
        superusers = [
            {'phone': u.phone, 'name': getattr(getattr(u, 'profile', None), 'full_name', '') or ''}
            for u in User.objects.filter(is_superuser=True, is_active=True).select_related('profile')
        ]
        return Response({
            'staff': rows, 'superusers': superusers,
            'sections': [{'key': k, 'label': label, 'hint': hint} for k, label, hint in SECTIONS],
            'roles': [{'code': code, 'label': label, 'permissions': perms} for code, (label, perms) in ROLES.items()]
            + [{'code': CUSTOM, 'label': 'Своя', 'permissions': None}],
        })

    def post(self, request):
        from .models import MonitorAccess

        phone = str(request.data.get('phone') or '').strip().replace(' ', '')
        password = str(request.data.get('password') or '')
        if not phone:
            raise ValidationError({'phone': 'Укажите телефон (он же логин).'})
        with transaction.atomic():
            user, created = User.objects.get_or_create(phone=phone)
            if user.is_superuser:
                raise ValidationError({'phone': 'Это суперюзер — ему доступно всё.'})
            if MonitorAccess.objects.filter(user=user).exists():
                raise ValidationError({'phone': 'У этого человека уже есть доступ — измените его в списке.'})
            if password:
                _set_password(user, password)
            elif created or not user.has_usable_password():
                raise ValidationError({'password': 'Задайте пароль — с ним сотрудник войдёт в панель.'})
            name = str(request.data.get('name') or '').strip()
            user.save()
            if name:
                from apps.users.models import Profile

                profile, _ = Profile.objects.get_or_create(user=user)
                if not profile.full_name:
                    profile.full_name = name[:200]
                    profile.save(update_fields=['full_name'])
            permissions = _permissions_from(request.data)
            access = MonitorAccess.objects.create(
                user=user, permissions=permissions, role=role_for(permissions),
                note=str(request.data.get('note') or '')[:200], created_by=request.user,
            )
        audit(request, 'staff.create', staff=user.phone, role=access.role)
        return Response(_staff_row(access), status=201)


class StaffDetailView(MonitorView):
    section = 'staff'

    def _get(self, pk):
        from .models import MonitorAccess

        access = MonitorAccess.objects.select_related('user__profile', 'created_by').filter(pk=pk).first()
        if access is None:
            raise NotFound('Сотрудник не найден.')
        return access

    def patch(self, request, pk):
        access = self._get(pk)
        if access.user_id == request.user.pk and ('permissions' in request.data or 'role' in request.data):
            raise ValidationError({'detail': 'Свои права меняет другой администратор.'})
        if 'role' in request.data or 'permissions' in request.data:
            access.permissions = _permissions_from(request.data)
            access.role = role_for(access.permissions)
        if 'active' in request.data:
            access.is_active = bool(request.data['active'])
        if 'note' in request.data:
            access.note = str(request.data['note'] or '')[:200]
        access.save()
        if request.data.get('password'):
            _set_password(access.user, str(request.data['password']))
            access.user.save()
            from core.views import revoke_refresh_tokens

            revoke_refresh_tokens(access.user)
        audit(request, 'staff.update', staff=access.user.phone, role=access.role,
              active=access.is_active, password_changed=bool(request.data.get('password')))
        return Response(_staff_row(access))

    def delete(self, request, pk):
        access = self._get(pk)
        if access.user_id == request.user.pk:
            raise ValidationError({'detail': 'Нельзя убрать доступ у себя.'})
        phone = access.user.phone
        access.delete()
        audit(request, 'staff.delete', staff=phone)
        return Response(status=204)


class AuditView(MonitorView):
    section = 'staff'

    def get(self, request):
        from apps.notifications.models import AuditLog

        qs = AuditLog.objects.filter(action__startswith='panel.').select_related('user').order_by('-created_at')
        return _page(request, qs, lambda a: {
            'id': a.pk, 'who': a.user.phone if a.user_id else '', 'action': a.action[len('panel.'):],
            'details': a.metadata, 'at': _iso(a.created_at),
        })


# ─── Техподдержка ───────────────────────────────────────────────────────────

def _ticket_row(ticket):
    last = ticket.last_message
    return {
        'id': ticket.pk, 'who': ticket.who(), 'user': ticket.user_id, 'phone': ticket.user.phone if ticket.user_id else ticket.phone,
        'source': ticket.source, 'source_label': ticket.get_source_display(),
        'status': ticket.status, 'status_label': ticket.get_status_display(),
        'last_text': (last.text[:160] if last else ''), 'last_from_staff': bool(last and last.from_staff),
        'messages': ticket.message_count, 'created': _iso(ticket.created_at), 'updated': _iso(ticket.updated_at),
    }


def _tickets():
    from django.db.models import Count, Prefetch

    from apps.support.models import SupportMessage, SupportTicket

    return SupportTicket.objects.select_related('user__profile').annotate(message_count=Count('messages')).prefetch_related(
        Prefetch('messages', queryset=SupportMessage.objects.order_by('-created_at'), to_attr='latest'))


def _with_last(ticket):
    ticket.last_message = ticket.latest[0] if getattr(ticket, 'latest', None) else None
    return ticket


class SupportListView(MonitorView):
    section = 'support'

    def get(self, request):
        from django.db.models import Q

        from apps.support.models import SupportTicket

        qs = _tickets().order_by('-updated_at')
        status = request.query_params.get('status')
        if status == 'active':
            qs = qs.exclude(status=SupportTicket.STATUS_CLOSED)
        elif status:
            qs = qs.filter(status=status)
        q = request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(Q(phone__icontains=q) | Q(name__icontains=q) | Q(user__phone__icontains=q)
                           | Q(user__profile__full_name__icontains=q) | Q(messages__text__icontains=q)).distinct()
        response = _page(request, qs, lambda t: _ticket_row(_with_last(t)))
        response.data['waiting'] = SupportTicket.objects.filter(status=SupportTicket.STATUS_OPEN).count()
        return response


def _ticket_detail(ticket):
    data = _ticket_row(_with_last(ticket))
    data['page'] = ticket.page
    data['messages_list'] = [
        {'id': m.pk, 'text': m.text, 'from_staff': m.from_staff, 'staff_name': m.staff_name, 'at': _iso(m.created_at)}
        for m in sorted(ticket.latest, key=lambda m: m.created_at)
    ]
    return data


def _get_ticket(pk):
    ticket = _tickets().filter(pk=pk).first()
    if ticket is None:
        raise NotFound('Обращение не найдено.')
    return ticket


class SupportDetailView(MonitorView):
    section = 'support'

    def get(self, request, pk):
        return Response(_ticket_detail(_get_ticket(pk)))


class SupportReplyView(MonitorView):
    section = 'support'

    def post(self, request, pk):
        from apps.support import telegram as support_bot

        ticket = _get_ticket(pk)
        text = str(request.data.get('text') or '').strip()
        if not text:
            raise ValidationError({'text': 'Напишите ответ.'})
        profile = getattr(request.user, 'profile', None)
        name = getattr(profile, 'full_name', '') or 'Поддержка Rentoo'
        support_bot.staff_reply(ticket, text, name)
        support_bot.tell_agents(ticket, text)
        audit(request, 'support.reply', ticket=ticket.pk)
        return Response(_ticket_detail(_get_ticket(pk)))


class SupportStatusView(MonitorView):
    section = 'support'

    def post(self, request, pk):
        from apps.support.models import SupportTicket

        ticket = _get_ticket(pk)
        value = request.data.get('status')
        if value not in (SupportTicket.STATUS_OPEN, SupportTicket.STATUS_CLOSED):
            raise ValidationError({'status': 'open или closed.'})
        SupportTicket.objects.filter(pk=ticket.pk).update(status=value, updated_at=timezone.now())
        audit(request, f'support.{"close" if value == "closed" else "reopen"}', ticket=ticket.pk)
        return Response(_ticket_detail(_get_ticket(pk)))
