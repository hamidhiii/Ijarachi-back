"""
Права в админ-панели (back.rentoo.uz/admin): раздел → уровень.

    none — раздела не видно, view — смотреть, edit — смотреть и менять.

Роль — готовый набор уровней; выбранная роль заполняет матрицу, дальше её
можно поправить точечно (тогда роль — «Своя»). Суперюзеру можно всё.
"""
NONE, VIEW, EDIT = 'none', 'view', 'edit'
LEVELS = (NONE, VIEW, EDIT)
RANK = {NONE: 0, VIEW: 1, EDIT: 2}

SECTIONS = [
    ('analytics', 'Аналитика и онлайн', 'Обзор, аудитория, воронка входа, проблемы'),
    ('users', 'Пользователи', 'Карточки; менять — блокировать и разблокировать'),
    ('listings', 'Объявления и модерация', 'Менять — одобрять, отклонять, скрывать, разбирать жалобы'),
    ('billing', 'Тарифы и продвижение', 'Менять — выдавать и завершать тарифы, цены и права тарифов, топ/VIP'),
    ('payments', 'Платежи и выручка', 'Видеть деньги; менять — отмечать заказы оплаченными, отменять'),
    ('deals', 'Сделки и споры', 'Менять — закрывать споры (сколько залога удержать)'),
    ('kyc', 'Проверка личности', 'Паспорта; менять — подтверждать и отклонять'),
    ('support', 'Техподдержка', 'Обращения с сайта и кабинета; менять — отвечать и закрывать'),
    ('staff', 'Сотрудники и роли', 'Менять — добавлять сотрудников, роли и пароли'),
]
SECTION_KEYS = [key for key, _label, _hint in SECTIONS]


def _all(level, **overrides):
    return {key: overrides.get(key, level) for key in SECTION_KEYS}


ROLES = {
    'viewer': ('Наблюдатель', _all(VIEW, staff=NONE)),
    'moderator': ('Модератор', _all(NONE, analytics=VIEW, users=VIEW, listings=EDIT, kyc=EDIT, support=VIEW)),
    'support': ('Поддержка', _all(VIEW, users=EDIT, payments=NONE, staff=NONE, support=EDIT)),
    'finance': ('Финансы', _all(VIEW, payments=EDIT, billing=EDIT, deals=EDIT, listings=VIEW, staff=NONE)),
    'admin': ('Администратор', _all(EDIT)),
}
CUSTOM = 'custom'


def normalize(permissions):
    """Только известные разделы и уровни; пропущенное — none."""
    permissions = permissions or {}
    return {key: permissions.get(key) if permissions.get(key) in LEVELS else NONE for key in SECTION_KEYS}


def role_for(permissions):
    """Роль, чей набор совпадает с матрицей, иначе «Своя»."""
    permissions = normalize(permissions)
    for code, (_label, preset) in ROLES.items():
        if preset == permissions:
            return code
    return CUSTOM
