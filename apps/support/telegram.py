"""
Поддержка в Telegram: каждое сообщение из обращения уходит сотрудникам
(SUPPORT_TELEGRAM_CHAT_IDS) через CRM-бота. Сотрудник отвечает реплаем на это
сообщение — ответ появляется у человека на странице «Поддержка» и приходит ему
уведомлением. Кнопка «Закрыть» под сообщением закрывает обращение.
"""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

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


def _card_markup(pk):
    return {'inline_keyboard': [[{'text': '✅ Закрыть обращение', 'callback_data': f'{PREFIX}:close:{pk}'}]]}


def notify_agents(message, first=False):
    """Отправить сообщение пользователя сотрудникам (после коммита)."""
    def send():
        ticket = message.ticket
        for chat_id in agent_chat_ids():
            try:
                result = _api('sendMessage', {
                    'chat_id': chat_id, 'text': _card(ticket, message, first),
                    'reply_markup': _card_markup(ticket.pk),
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


@transaction.atomic
def staff_reply(ticket, text, staff_name):
    """Ответ поддержки в обращение — из Telegram или из панели."""
    message = SupportMessage.objects.create(ticket=ticket, text=text[:4000], from_staff=True, staff_name=staff_name)
    ticket.status = SupportTicket.STATUS_ANSWERED
    ticket.save(update_fields=['status', 'updated_at'])
    notify_user(ticket, text)
    return message


def tell_agents(ticket, text):
    """Ответ из панели — сотрудникам в Telegram, чтобы переписка там была полной."""
    def send():
        for chat_id in agent_chat_ids():
            try:
                result = _api('sendMessage', {'chat_id': chat_id, 'text': f'🖥 Ответ из панели в #{ticket.pk}:\n\n{text}'[:4000]})
            except Exception:
                logger.exception('Support: could not mirror panel reply to %s', chat_id)
                continue
            message_id = (result or {}).get('message_id')
            if message_id:
                SupportTelegramMessage.objects.get_or_create(chat_id=chat_id, message_id=message_id,
                                                             defaults={'ticket': ticket})
    transaction.on_commit(send)


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
    staff_reply(ticket, text, _staff_name(sender))
    reply = f'✅ Отправлено в обращение #{ticket.pk}.'
    if not ticket.user_id:
        reply += ' Человек без аккаунта увидит ответ на странице «Поддержка» с того же устройства.'
        if ticket.phone:
            reply += f' Телефон: {ticket.phone}'
    _api('sendMessage', {'chat_id': chat_id, 'text': reply, 'reply_parameters': {
        'message_id': message.get('message_id'), 'allow_sending_without_reply': True}})
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
    message = callback.get('message') or {}
    if len(parts) == 3 and parts[2].isdigit():
        pk = int(parts[2])
        if parts[1] == 'close':
            # Одно касание не закрывает: кнопка под каждой карточкой, промахнуться легко.
            _api('answerCallbackQuery', {'callback_query_id': callback.get('id')})
            _api('editMessageReplyMarkup', {'chat_id': chat_id, 'message_id': message.get('message_id'), 'reply_markup': {
                'inline_keyboard': [[
                    {'text': f'Да, закрыть #{pk}', 'callback_data': f'{PREFIX}:closeyes:{pk}'},
                    {'text': '← Не закрывать', 'callback_data': f'{PREFIX}:keep:{pk}'},
                ]]}})
            return True
        if parts[1] == 'closeyes':
            updated = SupportTicket.objects.filter(pk=pk).update(status=SupportTicket.STATUS_CLOSED, updated_at=timezone.now())
            logger.info('Support: ticket %s closed from Telegram by %s', pk, sender)
            _api('answerCallbackQuery', {'callback_query_id': callback.get('id'),
                                         'text': f'Обращение #{pk} закрыто' if updated else 'Не найдено'})
            _api('editMessageReplyMarkup', {'chat_id': chat_id, 'message_id': message.get('message_id'),
                                            'reply_markup': {'inline_keyboard': []}})
            return True
        if parts[1] == 'keep':
            _api('answerCallbackQuery', {'callback_query_id': callback.get('id')})
            _api('editMessageReplyMarkup', {'chat_id': chat_id, 'message_id': message.get('message_id'),
                                            'reply_markup': _card_markup(pk)})
            return True
    _api('answerCallbackQuery', {'callback_query_id': callback.get('id')})
    return True
