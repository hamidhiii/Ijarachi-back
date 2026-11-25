"""
Поддержка в Telegram: каждое сообщение из обращения уходит сотрудникам
(SUPPORT_TELEGRAM_CHAT_IDS) через CRM-бота. Сотрудник отвечает реплаем на это
сообщение — ответ появляется у человека на странице «Поддержка» и приходит ему
уведомлением. Кнопка «Закрыть» под сообщением закрывает обращение.
"""
import logging

from django.conf import settings
from django.db import transaction

from .models import SupportMessage, SupportTelegramMessage, SupportTicket

logger = logging.getLogger('apps.support')
PREFIX = 'sup'


def agent_chat_ids():
    raw = getattr(settings, 'SUPPORT_TELEGRAM_CHAT_IDS', '') or ''
    ids = []
    for part in str(raw).replace(';', ',').split(','):
        part = part.strip()
        if part.lstrip('-').isdigit():
            ids.append(int(part))
    return ids


def _api(method, payload):
    from apps.crm import telegram as bot

    return bot.api(method, payload)


def _card(ticket, message, first):
    where = dict(SupportTicket.SOURCE_CHOICES).get(ticket.source, ticket.source)
    head = f'🆘 Новое обращение #{ticket.pk}' if first else f'💬 Обращение #{ticket.pk}'
    lines = [head, f'{ticket.who()} · {where}']
    if ticket.user_id is None and ticket.phone:
        lines.append(f'Связь: {ticket.phone}')
    if first and ticket.page:
        lines.append(f'Страница: {ticket.page}')
    lines += ['', message.text, '', '↩️ Ответьте реплаем на это сообщение — ответ придёт человеку.']
    return '\n'.join(lines)[:4000]


def notify_agents(message, first=False):
    """Отправить сообщение пользователя сотрудникам (после коммита)."""
    def send():
        ticket = message.ticket
        for chat_id in agent_chat_ids():
            try:
                result = _api('sendMessage', {
                    'chat_id': chat_id, 'text': _card(ticket, message, first),
                    'reply_markup': {'inline_keyboard': [[
                        {'text': '✅ Закрыть обращение', 'callback_data': f'{PREFIX}:close:{ticket.pk}'},
                    ]]},
                })
            except Exception:
                logger.exception('Support: could not deliver ticket %s to %s', ticket.pk, chat_id)
                continue
            message_id = (result or {}).get('message_id')
            if message_id:
                SupportTelegramMessage.objects.get_or_create(chat_id=chat_id, message_id=message_id,
                                                             defaults={'ticket': ticket})
    transaction.on_commit(send)


def _staff_name(from_user):
    name = ' '.join(filter(None, [from_user.get('first_name'), from_user.get('last_name')])).strip()
    return name or 'Поддержка Rentoo'


def notify_user(ticket, text):
    if not ticket.user_id:
        return
    from apps.notifications.models import Notification
    from apps.notifications.tasks import create_notification

    base = settings.OWNER_FRONTEND_BASE_URL if ticket.source == SupportTicket.SOURCE_OWNER else settings.FRONTEND_BASE_URL
    transaction.on_commit(lambda: create_notification(ticket.user, Notification.TYPE_SYSTEM, {
        'title': 'Ответ поддержки', 'message': text[:300], 'link': base.rstrip('/') + '/support',
    }))


def handle_reply(message):
    """Реплай сотрудника на карточку обращения. True — сообщение обработано."""
    chat_id = (message.get('chat') or {}).get('id')
    sender = message.get('from') or {}
    reply_to = message.get('reply_to_message') or {}
    if not chat_id or chat_id not in agent_chat_ids() or sender.get('id') != chat_id or not reply_to:
        return False
    link = SupportTelegramMessage.objects.select_related('ticket').filter(
        chat_id=chat_id, message_id=reply_to.get('message_id')).first()
    if link is None:
        return False
    text = (message.get('text') or message.get('caption') or '').strip()
    if not text:
        _api('sendMessage', {'chat_id': chat_id, 'text': 'Пока можно ответить только текстом.'})
        return True
    ticket = link.ticket
    with transaction.atomic():
        SupportMessage.objects.create(ticket=ticket, text=text[:4000], from_staff=True, staff_name=_staff_name(sender))
        ticket.status = SupportTicket.STATUS_ANSWERED
        ticket.save(update_fields=['status', 'updated_at'])
        notify_user(ticket, text)
    reply = f'✅ Отправлено в обращение #{ticket.pk}.'
    if not ticket.user_id:
        reply += ' Человек без аккаунта увидит ответ на странице «Поддержка» с того же устройства.'
        if ticket.phone:
            reply += f' Телефон: {ticket.phone}'
    _api('sendMessage', {'chat_id': chat_id, 'text': reply, 'reply_to_message_id': message.get('message_id')})
    return True


def handle_callback(callback):
    """Кнопка под карточкой. True — это кнопка поддержки."""
    data = callback.get('data') or ''
    if not data.startswith(f'{PREFIX}:'):
        return False
    chat_id = ((callback.get('message') or {}).get('chat') or {}).get('id')
    sender = (callback.get('from') or {}).get('id')
    if chat_id not in agent_chat_ids() or sender != chat_id:
        _api('answerCallbackQuery', {'callback_query_id': callback.get('id')})
        return True
    parts = data.split(':')
    if len(parts) == 3 and parts[1] == 'close' and parts[2].isdigit():
        updated = SupportTicket.objects.filter(pk=int(parts[2])).update(status=SupportTicket.STATUS_CLOSED)
        _api('answerCallbackQuery', {'callback_query_id': callback.get('id'),
                                     'text': f'Обращение #{parts[2]} закрыто' if updated else 'Не найдено'})
        return True
    _api('answerCallbackQuery', {'callback_query_id': callback.get('id')})
    return True
