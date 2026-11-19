"""
CRM-бот прокатов — работа с бронями, не открывая кабинет.

Отдельный бот (CRM_BOT_TOKEN), не @rentoo_app и не бот кодов входа. Владелец
или менеджер подключает его из кабинета: «Подключить Telegram» выдаёт
одноразовую ссылку t.me/<бот>?start=<токен>, бот по ней запоминает чат
(CrmBotLink). Утреннее напоминание о выдаче или возврате приходит карточкой
брони с кнопками:

    забронировано → [✅ Выдано] [📅 Перенести] [✖️ Отмена]
    выдано        → [✅ Принято] [⚠️ Есть повреждение] [📅 Продлить]

Кнопка меняет бронь тем же save_reservation, что и кабинет (те же переходы
статусов и проверка остатков), карточка перерисовывается по новому состоянию.
`/bugun` (`/today`) присылает такие карточки на сегодня.

Права — как в кабинете: владелец или менеджер, тариф владельца с CRM
(access.editor_role). Тексты — узбекский или русский по языку Telegram.
Обновления приходят на POST /api/v1/telegram/webhook/crm/ (настраивает
`manage.py setup_crm_bot`).
"""
import hashlib
import logging
import secrets
from datetime import timedelta

import requests

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .access import editor_role
from .models import CrmBotLink, Reservation, StaffMember
from .services import CrmError, save_reservation

logger = logging.getLogger('apps.crm')

PREFIX = 'crm'
MOVE_DAYS = (1, 2, 7)
TODAY_LIMIT = 10
TODAY_COMMANDS = {'/bugun', '/today', '/segodnya', 'bugun', 'сегодня'}
INVITE_TTL = 60 * 60
INVITE_KEY = 'crm-bot-invite:{}'

TEXTS = {
    'uz': {
        'pickup_today': '📦 Bugun berish',
        'pickup_on': '📦 Berish: {date}',
        'return_today': '↩️ Bugun qaytaradi',
        'return_on': '↩️ Qaytarish: {date}',
        'returned': '✅ Qaytarildi',
        'cancelled': '✖️ Bekor qilindi',
        'days': '{n} kun',
        'sum': "so'm",
        'btn_issue': '✅ Berildi',
        'btn_return': '✅ Qaytarildi',
        'btn_damage': '⚠️ Shikastlangan',
        'btn_move': "📅 Ko'chirish",
        'btn_extend': '📅 Uzaytirish',
        'btn_cancel': '✖️ Bekor qilish',
        'btn_cancel_yes': 'Ha, bekor qilish',
        'btn_back': '← Orqaga',
        'btn_open': 'Kabinetda ochish',
        'plus_days': '+{n} kun',
        'move_hint': "Necha kunga ko'chiramiz?",
        'extend_hint': 'Necha kunga uzaytiramiz?',
        'cancel_hint': 'Bronni bekor qilasizmi?',
        'done_issued': 'Berildi',
        'done_returned': 'Qaytarildi',
        'done_damaged': 'Shikastlangan holda qaytarildi',
        'done_moved': "Ko'chirildi",
        'done_cancelled': 'Bekor qilindi',
        'damage_note': "Shikastlangan holda qaytarildi (Telegram'da belgilandi)",
        'no_access': "Bu bronni o'zgartira olmaysiz: u sizniki emas yoki CRM tarifi tugagan.",
        'not_linked': "Bot ulanmagan. Kabinetda «Telegram'ni ulash» tugmasini bosing.",
        'no_crm': 'CRM START tarifidan ishlaydi: {url}',
        'today_empty': "Bugun berish va qaytarish yo'q.",
        'today_more': "Yana {n} ta — kabinetda: {url}",
        'linked': "Tayyor, {name}! Endi bu yerga ertalab bugungi berish va qaytarishlar tugmalar bilan keladi.\n\n➕ Yangi bron — bron yozish, 📅 Bugun — bugungi ro'yxat, «Kabinet» tugmasi — to'liq kabinet.",
        'link_expired': "Havola eskirgan. Kabinetda «Telegram'ni ulash» tugmasini qayta bosing: {url}",
        'stale': "Bron holati allaqachon o'zgargan — karta yangilandi.",
        'help': "➕ Yangi bron — bron yozish, 📅 Bugun — bugungi berish va qaytarishlar. Mahsulotlar, ombor va mijozlar — kabinetda.",
        'start_hint': "Bu Rentoo prokatlari uchun CRM bot. Uni ulash uchun kabinetda «Telegram'ni ulash» tugmasini bosing: {url}",
    },
    'ru': {
        'pickup_today': '📦 Сегодня выдать',
        'pickup_on': '📦 Выдача: {date}',
        'return_today': '↩️ Сегодня вернут',
        'return_on': '↩️ Возврат: {date}',
        'returned': '✅ Возвращено',
        'cancelled': '✖️ Отменено',
        'days': '{n} дн.',
        'sum': 'сум',
        'btn_issue': '✅ Выдано',
        'btn_return': '✅ Принято',
        'btn_damage': '⚠️ Есть повреждение',
        'btn_move': '📅 Перенести',
        'btn_extend': '📅 Продлить',
        'btn_cancel': '✖️ Отмена',
        'btn_cancel_yes': 'Да, отменить',
        'btn_back': '← Назад',
        'btn_open': 'Открыть в кабинете',
        'plus_days': '+{n} дн.',
        'move_hint': 'На сколько дней перенести?',
        'extend_hint': 'На сколько дней продлить?',
        'cancel_hint': 'Отменить бронь?',
        'done_issued': 'Выдано',
        'done_returned': 'Принято',
        'done_damaged': 'Принято с повреждением',
        'done_moved': 'Перенесено',
        'done_cancelled': 'Отменено',
        'damage_note': 'Возвращено с повреждением (отмечено в Telegram)',
        'no_access': 'Эту бронь изменить нельзя: она не ваша или тариф с CRM закончился.',
        'not_linked': 'Бот не подключён. Нажмите «Подключить Telegram» в кабинете.',
        'no_crm': 'CRM работает с тарифа START: {url}',
        'today_empty': 'Сегодня выдач и возвратов нет.',
        'today_more': 'Ещё {n} — в кабинете: {url}',
        'linked': 'Готово, {name}! Теперь сюда по утрам будут приходить выдачи и возвраты на сегодня — с кнопками.\n\n➕ Новая бронь — записать бронь, 📅 Сегодня — список на сегодня, кнопка «Кабинет» — весь кабинет.',
        'link_expired': 'Ссылка устарела. Нажмите «Подключить Telegram» в кабинете ещё раз: {url}',
        'stale': 'Статус брони уже изменился — карточка обновлена.',
        'help': '➕ Новая бронь — записать бронь, 📅 Сегодня — выдачи и возвраты на сегодня. Товары, склад и клиенты — в кабинете.',
        'start_hint': 'Это CRM-бот для прокатов Rentoo. Чтобы подключить его, нажмите «Подключить Telegram» в кабинете: {url}',
    },
}


def _t(lang):
    return TEXTS.get(lang) or TEXTS['uz']


def token():
    return settings.CRM_BOT_TOKEN


def webhook_secret():
    """X-Telegram-Bot-Api-Secret-Token: выводится из токена, второй секрет в .env не нужен."""
    if not token():
        return ''
    return hashlib.sha256(f'rentoo-crm-webhook:{token()}'.encode()).hexdigest()


def language(code):
    return 'ru' if (code or '').lower().startswith('ru') else 'uz'


def api(method, payload):
    """Bot API от имени CRM-бота; `result` или None. Токен в лог не попадает."""
    if not token():
        logger.warning('CRM_BOT_TOKEN is not set, cannot call %s', method)
        return None
    try:
        response = requests.post(f'{settings.TELEGRAM_API_BASE_URL}/bot{token()}/{method}', json=payload, timeout=10)
        body = response.json()
    except Exception as exc:  # noqa: BLE001 — сеть или JSON: просто неудачный вызов
        logger.error('CRM bot %s failed: %s', method, str(exc).replace(token(), '***'))
        return None
    if not body.get('ok'):
        logger.warning('CRM bot %s: %s', method, body.get('description'))
        return None
    return body.get('result')


def _owner_url(path='/'):
    return settings.OWNER_FRONTEND_BASE_URL.rstrip('/') + path


def _day(value):
    return value.strftime('%d.%m')


def _money(value):
    return f'{int(value):,}'.replace(',', ' ')


def _person(user):
    profile = getattr(user, 'profile', None)
    return (profile and (profile.full_name or profile.shop_name)) or user.phone


# ─── Карточка брони ─────────────────────────────────────────────────────────

def render(reservation, lang, footer=''):
    """Текст карточки — целиком из состояния брони, поэтому её можно перерисовать."""
    t = _t(lang)
    today = timezone.localdate()
    status = reservation.status
    if status == Reservation.STATUS_BOOKED:
        header = t['pickup_today'] if reservation.start_date == today else t['pickup_on'].format(date=_day(reservation.start_date))
    elif status == Reservation.STATUS_ISSUED:
        header = t['return_today'] if reservation.end_date == today else t['return_on'].format(date=_day(reservation.end_date))
    else:
        header = t['returned'] if status == Reservation.STATUS_RETURNED else t['cancelled']

    days = (reservation.end_date - reservation.start_date).days + 1
    lines = [
        header,
        f'«{reservation.item.title}» × {reservation.quantity}',
        f'{_day(reservation.start_date)} — {_day(reservation.end_date)} ({t["days"].format(n=days)})',
    ]
    if reservation.client:
        lines.append('👤 ' + ' '.join(filter(None, [reservation.client.name, reservation.client.phone])))
    if reservation.price:
        lines.append(f'💰 {_money(reservation.price)} {t["sum"]}')
    if footer:
        lines += ['', footer]
    return '\n'.join(lines)


def _button(text, action, reservation):
    return {'text': text, 'callback_data': f'{PREFIX}:{action}:{reservation.pk}'}


def keyboard(reservation, lang, mode='main'):
    """Кнопки под карточкой: по статусу брони или подменю (перенос, отмена)."""
    t = _t(lang)
    issued = reservation.status == Reservation.STATUS_ISSUED
    rows = []
    if mode == 'move':
        rows.append([_button(t['plus_days'].format(n=n), f'mv{n}', reservation) for n in MOVE_DAYS])
        rows.append([_button(t['btn_back'], 'back', reservation)])
    elif mode == 'cancel':
        rows.append([_button(t['btn_cancel_yes'], 'cany', reservation)])
        rows.append([_button(t['btn_back'], 'back', reservation)])
    elif reservation.status == Reservation.STATUS_BOOKED:
        rows.append([_button(t['btn_issue'], 'iss', reservation)])
        rows.append([_button(t['btn_move'], 'mv', reservation), _button(t['btn_cancel'], 'can', reservation)])
    elif issued:
        rows.append([_button(t['btn_return'], 'ret', reservation)])
        rows.append([_button(t['btn_damage'], 'dmg', reservation), _button(t['btn_extend'], 'mv', reservation)])
    rows.append([{'text': t['btn_open'], 'url': _owner_url(f'/reservations/{reservation.pk}')}])
    return {'inline_keyboard': rows}


def send_card(chat_id, reservation, lang, footer=''):
    return api('sendMessage', {
        'chat_id': chat_id,
        'text': render(reservation, lang, footer),
        'reply_markup': keyboard(reservation, lang),
    })


# ─── Привязка чата ──────────────────────────────────────────────────────────

def invite_link(user):
    """Одноразовая ссылка t.me/<бот>?start=<токен> на час; None — бот не настроен."""
    if not token() or not settings.CRM_BOT_USERNAME:
        return None
    code = secrets.token_urlsafe(18)
    cache.set(INVITE_KEY.format(code), user.pk, INVITE_TTL)
    return f'https://t.me/{settings.CRM_BOT_USERNAME}?start={code}'


def handle_start(chat_id, from_user, text):
    """/start <токен из кабинета> — привязывает чат; без токена — подсказка."""
    from django.contrib.auth import get_user_model

    lang = language((from_user or {}).get('language_code'))
    t = _t(lang)
    parts = (text or '').split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ''
    if not code:
        link = _link_for(chat_id, from_user)
        if link is not None:
            send_today(chat_id, from_user)
        else:
            api('sendMessage', {'chat_id': chat_id, 'text': t['start_hint'].format(url=_owner_url('/'))})
        return
    # Ссылка одноразовая: забираем токен до привязки, второй переход не сработает.
    user_id = cache.get(INVITE_KEY.format(code))
    cache.delete(INVITE_KEY.format(code))
    user = get_user_model().objects.filter(pk=user_id, is_active=True).select_related('profile').first() if user_id else None
    if user is None:
        api('sendMessage', {'chat_id': chat_id, 'text': t['link_expired'].format(url=_owner_url('/'))})
        return
    # Один чат — один пользователь: чат, привязанный к другому, переходит сюда.
    CrmBotLink.objects.filter(chat_id=chat_id).exclude(user=user).delete()
    CrmBotLink.objects.update_or_create(user=user, defaults={
        'chat_id': chat_id, 'username': (from_user or {}).get('username') or '', 'language': lang,
    })
    logger.info('CRM bot linked: user %s -> chat %s', user.pk, chat_id)
    from .bot_booking import menu_keyboard

    api('sendMessage', {'chat_id': chat_id, 'text': t['linked'].format(name=_person(user)),
                        'reply_markup': menu_keyboard(lang)})


def _link_for(chat_id, from_user):
    """Привязка — только в личном чате того, кто пишет или нажимает."""
    sender = (from_user or {}).get('id')
    if not chat_id or not sender or chat_id != sender:
        return None
    return CrmBotLink.objects.select_related('user__profile').filter(chat_id=chat_id, user__is_active=True).first()


def _user_for(link):
    return link.user if link is not None else None


def _remember_language(link, from_user):
    lang = language((from_user or {}).get('language_code'))
    if link is not None and link.language != lang:
        CrmBotLink.objects.filter(pk=link.pk).update(language=lang)
    return lang


# ─── Нажатие кнопки ─────────────────────────────────────────────────────────

def _answer(callback_id, text='', alert=False):
    api('answerCallbackQuery', {'callback_query_id': callback_id, 'text': text[:200], 'show_alert': alert})


def _apply(reservation, action, lang, actor):
    """Меняет бронь; возвращает текст «что сделано»."""
    t = _t(lang)
    # Кнопка со старой карточки (нажали дважды, или в кабинете уже отметили):
    # нужный статус для действия — иначе отказ и свежая карточка.
    needs = {
        'iss': {Reservation.STATUS_BOOKED},
        'ret': {Reservation.STATUS_ISSUED},
        'dmg': {Reservation.STATUS_ISSUED},
    }.get(action, set(Reservation.OCCUPYING_STATUSES))
    if reservation.status not in needs:
        raise CrmError('INVALID_STATUS', t['stale'])
    if action == 'iss':
        data, done = {'status': Reservation.STATUS_ISSUED}, t['done_issued']
    elif action == 'ret':
        data, done = {'status': Reservation.STATUS_RETURNED}, t['done_returned']
    elif action == 'dmg':
        notes = '\n'.join(filter(None, [reservation.notes, t['damage_note']]))
        data, done = {'status': Reservation.STATUS_RETURNED, 'notes': notes}, t['done_damaged']
    elif action == 'cany':
        data, done = {'status': Reservation.STATUS_CANCELLED}, t['done_cancelled']
    else:
        days = int(action[2:])
        # Выданную вещь не «переносят», а продлевают: двигается только возврат.
        shift = timedelta(days=days)
        data = {'end_date': reservation.end_date + shift}
        if reservation.status == Reservation.STATUS_BOOKED:
            data['start_date'] = reservation.start_date + shift
        done = f'{t["done_moved"]}: {t["plus_days"].format(n=days)}'
    save_reservation(reservation.owner, data, instance=reservation, actor=actor)
    return done


def handle_callback(callback):
    """Обрабатывает callback_query с `crm:…`; False — кнопка не наша."""
    parts = (callback.get('data') or '').split(':')
    if len(parts) >= 3 and parts[0] == PREFIX and parts[1] == 'nb':
        from .bot_booking import handle_callback as new_booking

        new_booking(callback, ':'.join(parts[2:]))
        return True
    if len(parts) != 3 or parts[0] != PREFIX or not parts[2].isdigit():
        return False
    action, reservation_id = parts[1], int(parts[2])
    message = callback.get('message') or {}
    chat_id = (message.get('chat') or {}).get('id')
    from_user = callback.get('from') or {}

    link = _link_for(chat_id, from_user)
    lang = _remember_language(link, from_user)
    t = _t(lang)
    user = _user_for(link)
    reservation = (
        Reservation.objects.select_related('item', 'client', 'owner').filter(pk=reservation_id).first()
    )
    if user is None or reservation is None or not editor_role(user, reservation.owner):
        _answer(callback['id'], t['no_access'] if user else t['not_linked'], alert=True)
        return True

    target = {'chat_id': chat_id, 'message_id': message.get('message_id')}

    if action in ('mv', 'can', 'back'):
        mode = {'mv': 'move', 'can': 'cancel', 'back': 'main'}[action]
        _answer(callback['id'], {'move': t['extend_hint'] if reservation.status == Reservation.STATUS_ISSUED else t['move_hint'],
                                 'cancel': t['cancel_hint'], 'main': ''}[mode])
        api('editMessageReplyMarkup', {**target, 'reply_markup': keyboard(reservation, lang, mode)})
        return True

    if action not in ('iss', 'ret', 'dmg', 'cany') and not (action.startswith('mv') and action[2:] in {str(n) for n in MOVE_DAYS}):
        _answer(callback['id'])
        return True

    try:
        with transaction.atomic():
            # of=self: клиент необязателен (LEFT JOIN), а Postgres не блокирует
            # nullable-сторону внешнего соединения.
            fresh = Reservation.objects.select_for_update(of=('self',)).select_related('item', 'client', 'owner').get(pk=reservation_id)
            done = _apply(fresh, action, lang, user)
    except CrmError as exc:
        detail = exc.detail.get('detail') if isinstance(exc.detail, dict) else str(exc.detail)
        _answer(callback['id'], str(detail), alert=True)
        reservation.refresh_from_db()
        api('editMessageText', {**target, 'text': render(reservation, lang), 'reply_markup': keyboard(reservation, lang)})
        return True

    fresh.refresh_from_db()
    stamp = timezone.localtime().strftime('%H:%M')
    footer = f'✔️ {done} — {_person(user)}, {stamp}'
    _answer(callback['id'], done)
    api('editMessageText', {**target, 'text': render(fresh, lang, footer), 'reply_markup': keyboard(fresh, lang)})
    logger.info('CRM bot: reservation %s %s by user %s', reservation_id, action, user.pk)
    return True


# ─── Напоминание и /bugun ───────────────────────────────────────────────────

def send_reminder(user, reservation_id):
    """
    Утреннее напоминание карточкой с кнопками — если пользователь подключил
    CRM-бота. False — не отправлено (тогда уходит обычное уведомление).
    """
    link = CrmBotLink.objects.filter(user=user).first()
    if link is None or not token():
        return False
    reservation = Reservation.objects.select_related('item', 'client', 'owner').filter(pk=reservation_id).first()
    if reservation is None or reservation.status not in Reservation.OCCUPYING_STATUSES:
        return False
    if not editor_role(user, reservation.owner):
        return False
    return send_card(link.chat_id, reservation, link.language) is not None


def accounts_for(user):
    """Кабинеты, где пользователь может менять брони."""
    owners = [user] + [
        member.owner for member in
        StaffMember.objects.filter(user=user, role=StaffMember.ROLE_MANAGER).select_related('owner')
    ]
    return [owner for owner in owners if editor_role(user, owner)]


def send_today(chat_id, from_user):
    """Ответ на /bugun: карточки выдач и возвратов на сегодня."""
    link = _link_for(chat_id, from_user)
    lang = _remember_language(link, from_user)
    t = _t(lang)
    user = _user_for(link)
    if user is None:
        api('sendMessage', {'chat_id': chat_id, 'text': t['not_linked']})
        return
    owners = accounts_for(user)
    if not owners:
        api('sendMessage', {'chat_id': chat_id, 'text': t['no_crm'].format(url=_owner_url('/tariffs'))})
        return

    today = timezone.localdate()
    due = (
        Reservation.objects
        .filter(owner__in=owners)
        .filter(Q(start_date=today, status=Reservation.STATUS_BOOKED) | Q(end_date=today, status=Reservation.STATUS_ISSUED))
        .select_related('item', 'client', 'owner')
        .order_by('status', 'pk')
    )
    total = due.count()
    if not total:
        from .bot_booking import TEXTS as NB

        api('sendMessage', {'chat_id': chat_id, 'text': t['today_empty'], 'reply_markup': {'inline_keyboard': [
            [{'text': (NB.get(lang) or NB['uz'])['btn_new'], 'callback_data': f'{PREFIX}:nb:new'}],
        ]}})
        return
    for reservation in due[:TODAY_LIMIT]:
        send_card(chat_id, reservation, lang)
    if total > TODAY_LIMIT:
        api('sendMessage', {
            'chat_id': chat_id,
            'text': t['today_more'].format(n=total - TODAY_LIMIT, url=_owner_url('/reservations')),
        })


def send_help(chat_id, from_user):
    """Любой другой текст: что умеет бот (или как его подключить)."""
    link = _link_for(chat_id, from_user)
    lang = _remember_language(link, from_user)
    t = _t(lang)
    if link is None:
        api('sendMessage', {'chat_id': chat_id, 'text': t['start_hint'].format(url=_owner_url('/'))})
        return
    from .bot_booking import TEXTS as NB, cabinet_button, menu_keyboard

    nb = NB.get(lang) or NB['uz']
    api('sendMessage', {'chat_id': chat_id, 'text': t['help'], 'reply_markup': {'inline_keyboard': [
        [{'text': nb['btn_new'], 'callback_data': f'{PREFIX}:nb:new'},
         {'text': nb['btn_today'], 'callback_data': f'{PREFIX}:nb:today'}],
        [cabinet_button(lang)],
    ]}})
    # Нижние кнопки — если клиент их скрыл или подключался до их появления.
    api('sendMessage', {'chat_id': chat_id, 'text': nb['menu'], 'reply_markup': menu_keyboard(lang)})


def is_today_command(text):
    word = (text or '').strip().split('@')[0].split(maxsplit=1)
    return bool(word) and word[0].lower() in TODAY_COMMANDS
