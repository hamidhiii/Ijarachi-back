"""
Новая бронь в CRM-боте — кнопками, не открывая кабинет.

    ➕ Yangi bron → (кабинет, если их несколько) → товар → дата выдачи →
    сколько дней → сколько штук → откуда клиент → клиент (имя и телефон
    текстом или «пропустить») → проверка → ✅ Saqlash

Черновик — в кэше на чат (30 минут), кнопки — `crm:nb:<шаг><значение>`.
Дату, число дней, штук и клиента можно и написать текстом. Сохраняет тот же
save_reservation, что и кабинет: остатки проверяются под блокировкой, и
бронь «на последние штуки» дважды не пройдёт. После сохранения сообщение
становится обычной карточкой брони с кнопками «Выдано», «Перенести», «Отмена».
"""
import re
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Item

from . import telegram as bot
from .access import editor_role
from .models import Reservation
from .services import CrmError, free_units, save_reservation

DRAFT_KEY = 'crm-bot-draft:{}'
DRAFT_TTL = 30 * 60
PAGE = 8
DAY_CHOICES = (1, 2, 3, 4, 5, 7, 10, 14)
NEW_COMMANDS = {'/yangi', '/new', '/novaya', '/bron'}

TEXTS = {
    'uz': {
        'btn_new': '➕ Yangi bron',
        'btn_today': '📅 Bugun',
        'btn_cabinet': '📱 Kabinet',
        'btn_skip': "O'tkazib yuborish →",
        'btn_save': '✅ Saqlash',
        'btn_abort': '✖️ Bekor',
        'btn_more': 'Yana →',
        'btn_add_product': "➕ Mahsulot qo'shish",
        'today': 'Bugun',
        'tomorrow': 'Ertaga',
        'weekdays': ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya'],
        'ask_account': 'Qaysi kabinet uchun?',
        'ask_item': 'Qaysi mahsulot?',
        'ask_start': '«{item}» — qachon berasiz?\nYoki sanani yozing: 25.11',
        'ask_days': '«{item}», {start} dan — necha kunga?\nYoki raqam yozing.',
        'ask_qty': '{dates} — bo\'sh {free} ta. Nechta?',
        'ask_source': 'Mijoz qayerdan?',
        'ask_client': "Mijoz ismi va telefoni — bir xabarda, masalan:\nAziz +998901234567",
        'confirm': "Tekshiring:\n\n«{item}» × {qty}\n{dates} ({days})\n{client}💰 {price} so'm\n\nSaqlaymizmi?",
        'no_client': '',
        'no_items': "Hali mahsulot yo'q. Kabinetda «Qoldiqlar» → «Mahsulot qo'shish».",
        'none_free': "Bu kunlarga bo'sh yo'q. Boshqa sanani tanlang.",
        'bad_date': 'Sanani tushunmadim. Masalan: 25.11',
        'bad_number': 'Raqam yozing, masalan: 3',
        'too_many': "Bo'sh {free} ta, ko'prog'ini bron qilib bo'lmaydi.",
        'expired': "Bron qoralamasi eskirgan — boshidan boshlang: ➕ Yangi bron",
        'aborted': 'Bekor qilindi.',
        'saved': 'Saqlandi',
        'sources': {'phone': '📞 Qo\'ng\'iroq', 'instagram': 'Instagram', 'rentoo': 'Rentoo', 'other': 'Boshqa'},
        'menu': 'Nima qilamiz?',
    },
    'ru': {
        'btn_new': '➕ Новая бронь',
        'btn_today': '📅 Сегодня',
        'btn_cabinet': '📱 Кабинет',
        'btn_skip': 'Пропустить →',
        'btn_save': '✅ Сохранить',
        'btn_abort': '✖️ Отмена',
        'btn_more': 'Ещё →',
        'btn_add_product': '➕ Добавить товар',
        'today': 'Сегодня',
        'tomorrow': 'Завтра',
        'weekdays': ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'],
        'ask_account': 'Для какого кабинета?',
        'ask_item': 'Какой товар?',
        'ask_start': '«{item}» — когда выдаёте?\nИли напишите дату: 25.11',
        'ask_days': '«{item}» с {start} — на сколько дней?\nИли напишите число.',
        'ask_qty': '{dates} — свободно {free} шт. Сколько?',
        'ask_source': 'Откуда клиент?',
        'ask_client': 'Имя и телефон клиента — одним сообщением, например:\nАзиз +998901234567',
        'confirm': 'Проверьте:\n\n«{item}» × {qty}\n{dates} ({days})\n{client}💰 {price} сум\n\nСохранить?',
        'no_client': '',
        'no_items': 'Товаров пока нет. В кабинете: «Остатки» → «Добавить товар».',
        'none_free': 'На эти даты свободных нет. Выберите другую дату.',
        'bad_date': 'Не понял дату. Например: 25.11',
        'bad_number': 'Напишите число, например: 3',
        'too_many': 'Свободно {free} шт., больше забронировать нельзя.',
        'expired': 'Черновик брони устарел — начните заново: ➕ Новая бронь',
        'aborted': 'Отменено.',
        'saved': 'Сохранено',
        'sources': {'phone': '📞 Звонок', 'instagram': 'Instagram', 'rentoo': 'Rentoo', 'other': 'Другое'},
        'menu': 'Что делаем?',
    },
}


def _t(lang):
    return TEXTS.get(lang) or TEXTS['uz']


def is_new_command(text):
    word = (text or '').strip().split('@')[0]
    return word.lower() in NEW_COMMANDS or word in {TEXTS['uz']['btn_new'], TEXTS['ru']['btn_new']}


def is_today_button(text):
    return (text or '').strip() in {TEXTS['uz']['btn_today'], TEXTS['ru']['btn_today']}


def menu_keyboard(lang):
    """Постоянные кнопки внизу чата: новая бронь и сегодня."""
    t = _t(lang)
    return {'keyboard': [[{'text': t['btn_new']}, {'text': t['btn_today']}]], 'resize_keyboard': True,
            'is_persistent': True}


def cabinet_button(lang, path='/'):
    return {'text': _t(lang)['btn_cabinet'], 'web_app': {'url': bot._owner_url(path)}}


# ─── Черновик ───────────────────────────────────────────────────────────────

def _load(chat_id):
    return cache.get(DRAFT_KEY.format(chat_id))


def _store(chat_id, draft):
    cache.set(DRAFT_KEY.format(chat_id), draft, DRAFT_TTL)


def _drop(chat_id):
    cache.delete(DRAFT_KEY.format(chat_id))


def _btn(text, value):
    return {'text': text, 'callback_data': f'{bot.PREFIX}:nb:{value}'}


def _abort_row(t):
    return [_btn(t['btn_abort'], 'x')]


def _day_label(day, t):
    today = timezone.localdate()
    if day == today:
        return t['today']
    if day == today + timedelta(days=1):
        return t['tomorrow']
    return f'{t["weekdays"][day.weekday()]} {day:%d.%m}'


def _dates(draft):
    start = date.fromisoformat(draft['start'])
    end = start + timedelta(days=draft['days'] - 1)
    return start, end


def _dates_label(draft):
    start, end = _dates(draft)
    return f'{start:%d.%m} — {end:%d.%m}'


# ─── Шаги ───────────────────────────────────────────────────────────────────

def _say(chat_id, text, keyboard, edit_message_id=None):
    payload = {'chat_id': chat_id, 'text': text, 'reply_markup': {'inline_keyboard': keyboard}}
    if edit_message_id:
        if bot.api('editMessageText', {**payload, 'message_id': edit_message_id}) is not None:
            return
    bot.api('sendMessage', payload)


def _items(owner):
    return (
        Item.objects.filter(owner=owner)
        .exclude(status__in=[Item.STATUS_INACTIVE, Item.STATUS_REJECTED, Item.STATUS_BLOCKED])
        .order_by('title', 'pk')
    )


def _step(chat_id, draft, lang, edit=None):
    """Показывает следующий незаполненный шаг черновика."""
    t = _t(lang)
    owner_id = draft.get('owner')
    if owner_id is None:
        rows = [[_btn(name, f'a{pk}')] for pk, name in draft['accounts']]
        return _say(chat_id, t['ask_account'], rows + [_abort_row(t)], edit)

    if draft.get('item') is None:
        items = list(_items(owner_id))
        if not items:
            _drop(chat_id)
            return _say(chat_id, t['no_items'], [[{**cabinet_button(lang, '/stock'), 'text': t['btn_add_product']}]], edit)
        page = draft.get('page', 0)
        chunk = items[page * PAGE:(page + 1) * PAGE]
        rows = [[_btn(f'{item.title} · {item.quantity}', f'i{item.pk}')] for item in chunk]
        nav = []
        if len(items) > (page + 1) * PAGE:
            nav.append(_btn(t['btn_more'], f'p{page + 1}'))
        return _say(chat_id, t['ask_item'], rows + ([nav] if nav else []) + [_abort_row(t)], edit)

    item = Item.objects.get(pk=draft['item'])
    if draft.get('start') is None:
        today = timezone.localdate()
        days = [today + timedelta(days=n) for n in range(8)]
        rows = [[_btn(_day_label(d, t), f'd{d:%Y%m%d}') for d in days[i:i + 4]] for i in (0, 4)]
        draft['await'] = 'start'
        _store(chat_id, draft)
        return _say(chat_id, t['ask_start'].format(item=item.title), rows + [_abort_row(t)], edit)

    if draft.get('days') is None:
        start = date.fromisoformat(draft['start'])
        rows = [[_btn(bot._t(lang)['days'].format(n=n), f'n{n}') for n in DAY_CHOICES[i:i + 4]] for i in (0, 4)]
        draft['await'] = 'days'
        _store(chat_id, draft)
        return _say(chat_id, t['ask_days'].format(item=item.title, start=_day_label(start, t)), rows + [_abort_row(t)], edit)

    start, end = _dates(draft)
    free = free_units(item, start, end)
    if free <= 0:
        draft['start'] = draft['days'] = None
        _store(chat_id, draft)
        bot.api('sendMessage', {'chat_id': chat_id, 'text': t['none_free']})
        return _step(chat_id, draft, lang)

    if draft.get('qty') is None:
        if free == 1 or item.quantity == 1:
            draft['qty'] = 1
        else:
            options = list(range(1, min(free, 8) + 1))
            rows = [[_btn(str(n), f'q{n}') for n in options[i:i + 4]] for i in range(0, len(options), 4)]
            if free > 8:
                rows.append([_btn(f'{free}', f'q{free}')])
            draft['await'] = 'qty'
            _store(chat_id, draft)
            return _say(chat_id, t['ask_qty'].format(dates=_dates_label(draft), free=free), rows + [_abort_row(t)], edit)

    if draft.get('source') is None:
        sources = t['sources']
        rows = [[_btn(sources['phone'], 'sphone'), _btn(sources['instagram'], 'sinstagram')],
                [_btn(sources['rentoo'], 'srentoo'), _btn(sources['other'], 'sother')]]
        draft['await'] = None
        _store(chat_id, draft)
        return _say(chat_id, t['ask_source'], rows + [_abort_row(t)], edit)

    if draft.get('client') is None:
        draft['await'] = 'client'
        _store(chat_id, draft)
        return _say(chat_id, t['ask_client'], [[_btn(t['btn_skip'], 'c')], _abort_row(t)], edit)

    draft['await'] = None
    _store(chat_id, draft)
    name, phone = draft['client']
    client = ('👤 ' + ' '.join(filter(None, [name, phone])) + '\n') if (name or phone) else ''
    price = Decimal(item.price_per_day) * draft['days'] * draft['qty']
    text = t['confirm'].format(
        item=item.title, qty=draft['qty'], dates=_dates_label(draft),
        days=bot._t(lang)['days'].format(n=draft['days']), client=client, price=bot._money(price),
    )
    return _say(chat_id, text, [[_btn(t['btn_save'], 'ok')], _abort_row(t)], edit)


def _user_and_lang(chat_id, from_user):
    link = bot._link_for(chat_id, from_user)
    lang = bot._remember_language(link, from_user)
    return bot._user_for(link), lang


def start(chat_id, from_user, edit=None):
    """«➕ Новая бронь»: новый черновик и первый шаг."""
    user, lang = _user_and_lang(chat_id, from_user)
    if user is None:
        bot.api('sendMessage', {'chat_id': chat_id, 'text': bot._t(lang)['not_linked']})
        return
    owners = bot.accounts_for(user)
    if not owners:
        bot.api('sendMessage', {'chat_id': chat_id, 'text': bot._t(lang)['no_crm'].format(url=bot._owner_url('/tariffs'))})
        return
    draft = {'user': user.pk, 'owner': owners[0].pk if len(owners) == 1 else None,
             'accounts': [(o.pk, bot._person(o)) for o in owners]}
    _store(chat_id, draft)
    _step(chat_id, draft, lang, edit)


def _parse_date(text):
    match = re.fullmatch(r'\s*(\d{1,2})[./\-](\d{1,2})(?:[./\-](\d{2,4}))?\s*', text or '')
    if not match:
        return None
    today = timezone.localdate()
    day, month, year = int(match[1]), int(match[2]), match[3]
    try:
        if year:
            year = int(year) + (2000 if len(year) == 2 else 0)
            return date(year, month, day)
        value = date(today.year, month, day)
        # «05.01» в декабре — это следующий январь.
        return value if value >= today - timedelta(days=1) else date(today.year + 1, month, day)
    except ValueError:
        return None


PHONE = re.compile(r'\+?\d[\d\s\-()]{6,}\d')


def _parse_client(text):
    text = (text or '').strip()
    match = PHONE.search(text)
    phone = re.sub(r'[^\d+]', '', match[0]) if match else ''
    if phone and not phone.startswith('+') and len(phone) == 9:
        phone = '+998' + phone
    elif phone and not phone.startswith('+') and phone.startswith('998'):
        phone = '+' + phone
    name = (PHONE.sub(' ', text) if match else text).strip(' ,;-')[:200]
    return name, phone


def handle_text(chat_id, from_user, text):
    """Текст во время черновика (дата, дни, штуки, клиент). False — черновика, ждущего текст, нет."""
    draft = _load(chat_id)
    if not draft or not draft.get('await'):
        return False
    user, lang = _user_and_lang(chat_id, from_user)
    t = _t(lang)
    if user is None or user.pk != draft['user']:
        return False
    waiting = draft['await']
    if waiting == 'start':
        day = _parse_date(text)
        if day is None or day < timezone.localdate() - timedelta(days=1):
            bot.api('sendMessage', {'chat_id': chat_id, 'text': t['bad_date']})
            return True
        draft['start'] = day.isoformat()
    elif waiting in ('days', 'qty'):
        digits = re.sub(r'\D', '', text or '')
        if not digits or int(digits) < 1:
            bot.api('sendMessage', {'chat_id': chat_id, 'text': t['bad_number']})
            return True
        number = int(digits)
        if waiting == 'days':
            draft['days'] = min(number, 366)
        else:
            item = Item.objects.get(pk=draft['item'])
            start, end = _dates(draft)
            free = free_units(item, start, end)
            if number > free:
                bot.api('sendMessage', {'chat_id': chat_id, 'text': t['too_many'].format(free=free)})
                return True
            draft['qty'] = number
    elif waiting == 'client':
        draft['client'] = _parse_client(text)
    _store(chat_id, draft)
    _step(chat_id, draft, lang)
    return True


def handle_callback(callback, value):
    """Кнопка `crm:nb:<value>`."""
    message = callback.get('message') or {}
    chat_id = (message.get('chat') or {}).get('id')
    message_id = message.get('message_id')
    from_user = callback.get('from') or {}
    user, lang = _user_and_lang(chat_id, from_user)
    t = _t(lang)
    bot._answer(callback['id'])
    if user is None:
        bot.api('sendMessage', {'chat_id': chat_id, 'text': bot._t(lang)['not_linked']})
        return
    if value == 'new':
        return start(chat_id, from_user)
    if value == 'today':
        return bot.send_today(chat_id, from_user)

    draft = _load(chat_id)
    if not draft or draft.get('user') != user.pk:
        return _say(chat_id, t['expired'], [[_btn(t['btn_new'], 'new')]], message_id)
    if value == 'x':
        _drop(chat_id)
        return _say(chat_id, t['aborted'], [], message_id)

    kind, rest = value[:1], value[1:]
    if kind == 'a' and rest.isdigit() and int(rest) in {pk for pk, _ in draft['accounts']}:
        draft['owner'] = int(rest)
    elif kind == 'p' and rest.isdigit():
        draft['page'] = int(rest)
    elif kind == 'i' and rest.isdigit() and _items(draft['owner']).filter(pk=int(rest)).exists():
        draft['item'] = int(rest)
    elif kind == 'd' and rest.isdigit():
        try:
            draft['start'] = date(int(rest[:4]), int(rest[4:6]), int(rest[6:8])).isoformat()
        except ValueError:
            pass
    elif kind == 'n' and rest.isdigit():
        draft['days'] = int(rest)
    elif kind == 'q' and rest.isdigit():
        draft['qty'] = int(rest)
    elif kind == 's' and rest in dict(Reservation.SOURCE_CHOICES):
        draft['source'] = rest
    elif value == 'c':
        draft['client'] = ('', '')
    elif value == 'ok':
        return _save(chat_id, message_id, draft, user, lang)
    _store(chat_id, draft)
    _step(chat_id, draft, lang, message_id)


def _save(chat_id, message_id, draft, user, lang):
    t = _t(lang)
    owner_model = Item._meta.get_field('owner').remote_field.model
    owner = owner_model.objects.filter(pk=draft['owner']).first()
    if owner is None or not editor_role(user, owner):
        _drop(chat_id)
        return _say(chat_id, bot._t(lang)['no_access'], [], message_id)
    item = Item.objects.get(pk=draft['item'])
    start, end = _dates(draft)
    name, phone = draft['client']
    data = {
        'item': item, 'start_date': start, 'end_date': end, 'quantity': draft['qty'],
        'source': draft['source'], 'price': Decimal(item.price_per_day) * draft['days'] * draft['qty'],
        'client_name': name, 'client_phone': phone,
    }
    try:
        with transaction.atomic():
            reservation = save_reservation(owner, data, actor=user)
    except CrmError as exc:
        detail = exc.detail.get('detail') if isinstance(exc.detail, dict) else str(exc.detail)
        draft['qty'] = None
        _store(chat_id, draft)
        bot.api('sendMessage', {'chat_id': chat_id, 'text': str(detail)})
        return _step(chat_id, draft, lang)
    _drop(chat_id)
    reservation = Reservation.objects.select_related('item', 'client', 'owner').get(pk=reservation.pk)
    footer = f'✔️ {t["saved"]} — {bot._person(user)}, {timezone.localtime():%H:%M}'
    payload = {'chat_id': chat_id, 'text': bot.render(reservation, lang, footer),
               'reply_markup': bot.keyboard(reservation, lang)}
    if bot.api('editMessageText', {**payload, 'message_id': message_id}) is None:
        bot.api('sendMessage', payload)
