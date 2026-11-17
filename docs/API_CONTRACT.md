# Rentoo API — контракт доски объявлений

Новые и изменённые эндпоинты после перехода на доску объявлений с платными
тарифами (ветка `feat/listing-board`, ТЗ от 16.11.2026). Для фронта rentoo.uz и
кабинета owner.rentoo.uz. Как это устроено внутри — [PROJECT_OVERVIEW.md](../PROJECT_OVERVIEW.md),
полная схема — Swagger `/api/docs/`.

Примеры ответов сняты с настоящих запросов к API (тестовые данные).

## Содержание

1. [Общее](#1-общее)
2. [Что изменилось в объявлении](#2-что-изменилось-в-объявлении)
3. [Сделка выключена: 410](#3-сделка-выключена-410)
4. [Тарифы и подписка](#4-тарифы-и-подписка)
5. [Заказы и оплата: Click, Payme, return URL](#5-заказы-и-оплата-click-payme-return-url)
6. [Продвижение: топ и VIP](#6-продвижение-топ-и-vip)
7. [Показать номер](#7-показать-номер)
8. [Жалобы](#8-жалобы)
9. [Кабинет владельца `/api/v1/owner/`](#9-кабинет-владельца-apiv1owner)
10. [Модерация (сотрудники)](#10-модерация-сотрудники)
11. [Админка тарифов (сотрудники)](#11-админка-тарифов-сотрудники)
12. [Обработчики Click и Payme (для провайдеров)](#12-обработчики-click-и-payme-для-провайдеров)
13. [Все коды ошибок](#13-все-коды-ошибок)

---

## 1. Общее

- База: `https://back.rentoo.uz/api/v1`. Ниже пути — от `/api/v1`.
- Авторизация: заголовок `X-Auth-Token: Bearer <access>` (как раньше).
- Деньги — строки целых сумов (`"99000"`), кроме `price` в `GET /billing/promotions/` и чисел в метриках.
- Даты — `YYYY-MM-DD`, время — ISO 8601 с поясом Ташкента (`+05:00`).
- Ошибки — `{"code": "...", "detail": "..."}` (+ доп. поля, где указано).
  Ошибки валидации полей — `{"<поле>": ["текст"], "code": "validation_error"}`.
  Нет токена — 401 `not_authenticated`, не сотрудник на admin-эндпоинте — 403 `permission_denied`.
- Пагинация (где отмечено «список, страницы»): `{"count", "next", "previous", "results"}`, по 20, `?page=N`.
- Троттлинг: 429 `{"code": "throttled", "detail": "..."}` и заголовок `Retry-After` (секунды).

### Тарифы и права — шпаргалка

| Тариф | Цена/мес | Активных объявлений | CRM | Приоритет в выдаче | Сотрудники | Статистика | Филиалы | Выгрузка |
|---|---|---|---|---|---|---|---|---|
| `free` | 0 | 10 | — | — | — | — | — | — |
| `start` | 99 000 | 100 | ✓ | — | — | — | — | — |
| `business` | 199 000 | 300 | ✓ | ✓ | ✓ | ✓ | — | — |
| `pro` | 399 000 | без лимита | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

**CRM** (17.11.2026) — весь `/api/v1/owner/...`, кроме `GET /owner/accounts/`, с тарифа
START. На FREE — 403 `{code: PLAN_FEATURE_REQUIRED, feature: "crm", required_plan: "start"}`;
записи CRM не удаляются, напоминания о выдаче и возврате не приходят. `GET /owner/accounts/`
открыт на любом тарифе: по `plan` фронт решает, показать кабинет или тарифы. Поле `crm`
добавлено в `GET /billing/plans/`.

«Активное» объявление — `pending` или `approved`. Месяц тарифа — 30 дней.

---

## 2. Что изменилось в объявлении

### Новые поля

| Поле | Где | Тип | Что |
|---|---|---|---|
| `quantity` | список, карточка, создание, правка | int ≥ 1 | сколько одинаковых вещей в объявлении. Меняется без повторной модерации. Нельзя уменьшить ниже уже забронированного на будущие дни (400 `quantity`) |
| `is_vip` | список, карточка | bool | VIP действует сейчас |
| `is_top` | список, карточка | bool | «топ» действует сейчас |
| `vip_until`, `top_until` | карточка | datetime \| null | до когда действует продвижение |
| `owner.myid_verified` | список, карточка | bool | значок «Проверен MyID» |

`myid_verified` также появился в `GET /profile/` и `GET /users/{id}/`.

Пример строки списка `GET /listings/` (фрагмент):

```json
{
  "id": 1, "title": "Свадебные стулья", "price_per_day": "100000", "deposit": "50000",
  "quantity": 10, "is_vip": false, "is_top": false, "status": "approved",
  "owner": {"id": 1, "full_name": "", "shop_name": "", "account_type": "private",
            "avatar": null, "rating": 0.0, "verified": false, "myid_verified": false}
}
```

### Статус `blocked`

Новое значение `status`: **`blocked`** — «Скрыто модератором». Такое объявление:
- не видно в каталоге и по прямой ссылке (404);
- видно владельцу в `GET /items/my/` со `status: "blocked"`; причину он получает в уведомлении «Объявление скрыто»;
- не считается в лимите тарифа;
- владелец не может вернуть его сам: `PATCH {"status": ...}` → 400
  `{"status": ["Объявление скрыто модератором — вернуть его может только поддержка."], "code": "validation_error"}`;
  `DELETE` ничего не меняет (остаётся `blocked`).

Все статусы: `pending`, `approved`, `rejected`, `inactive`, `blocked`.

### Порядок выдачи

`GET /listings/` (и `/catalog/`) **без** `ordering`: VIP → топ → владельцы на
BUSINESS/PRO → новее. Явная сортировка (`ordering=price`, `-price`, `date`,
`relevance` с `q`, `-view_count` и т. п.) работает как раньше.

### Лимит объявлений — `LIMIT_REACHED`

Проверяется при создании (`POST /listings/`, `POST /items/create/`) и при
активации (`PATCH /listings/{id}/` со `status: "pending"` у снятого или
отклонённого). Было: 400 `listing_limit`. Стало:

```json
HTTP 400
{
  "code": "LIMIT_REACHED",
  "detail": "На тарифе FREE можно держать не больше 10 активных объявлений. Снимите одно из старых или перейдите на тариф выше.",
  "plan": "free", "limit": 10, "active": 10
}
```

### Профиль

`GET /profile/`: `listing_limit` теперь по тарифу (`null` — без лимита, PRO),
`live_listings` — активных сейчас, добавлено `myid_verified`. Тип аккаунта
`shop` лимит больше не повышает (остаются бейдж «Магазин» и часы работы).

### Объявления, снятые по окончании тарифа

Когда платный тариф заканчивается, объявления сверх лимита FREE получают
`status: "inactive"` (не удаляются). После новой оплаты тарифа они
возвращаются сами. Если владелец сам поменял статус такого объявления — оно
больше не возвращается. Сколько таких сейчас — `paused_listings` в
`GET /billing/subscription/`.

### `GET /listings/my/stats/`

Было: только магазину, 403 `shop_only`. Стало: тариф BUSINESS+, иначе 403
`PLAN_FEATURE_REQUIRED`. Помесячная статистика — `GET /owner/stats/`.

---

## 3. Сделка выключена: 410

Пока на сервере `DEAL_FLOW_ENABLED=False` (по умолчанию), все эндпоинты сделки
отвечают **410** — до проверки авторизации, так что и аноним получает 410, а не 401:

```json
HTTP 410
{"code": "DEAL_FLOW_DISABLED", "detail": "Сделки через платформу отключены: свяжитесь с владельцем в чате или по телефону."}
```

Затронуты: `deals/`, `deals/preview/`, `deals/list/`, `deals/{id}/`, `deals/{id}/pay/`,
`deals/{id}/review/`, `deals/{id}/photos/`, `deals/{id}/confirm-return/`,
`deals/{id}/dispute/`, `deals/{id}/resolve-dispute/`, `deals/{id}/status/`,
`bookings/create/`, `bookings/{id}/`, `bookings/{id}/status/`, `my-rentals/`,
`pricing/payout/`, `offers/`, `offers/{id}/respond/`, вебхуки
`payments/{payme,click}/{webhook,callback}/`.

Работают как раньше: отзывы на чтение (`users/{id}/reviews/`, `profile/reviews/`,
`listings/{id}/reviews/`), чат, избранное, календарь `listings/{id}/availability/`.

---

## 4. Тарифы и подписка

### `GET /billing/plans/` — список тарифов

Без авторизации. Массив без страниц, по возрастанию `rank`.

```json
[
  {"code": "free", "name": "FREE", "price": "0", "listing_limit": 10,
   "search_priority": false, "staff_access": false, "statistics": false,
   "branches": false, "data_export": false, "rank": 0},
  {"code": "business", "name": "BUSINESS", "price": "199000", "listing_limit": 300,
   "search_priority": true, "staff_access": true, "statistics": true,
   "branches": false, "data_export": false, "rank": 2},
  {"code": "pro", "name": "PRO", "price": "399000", "listing_limit": null,
   "search_priority": true, "staff_access": true, "statistics": true,
   "branches": true, "data_export": true, "rank": 3}
]
```

### `GET /billing/subscription/` — мой тариф сейчас

Авторизация. `ends_at`/`days_left` — `null` на FREE.

```json
{
  "plan": {"code": "start", "name": "START", "price": "99000", "listing_limit": 100, "...": "..."},
  "is_paid": true,
  "ends_at": "2026-12-16T09:18:46.220460+05:00",
  "days_left": 30,
  "listing_limit": 100,
  "live_listings": 1,
  "paused_listings": 0
}
```

### Правила смены тарифа

- **Тот же тариф** — новый период начинается с конца текущего (продление вперёд).
- **Тариф выше** — начинается сразу; неиспользованный остаток старого тарифа
  пересчитывается по цене в дни нового и добавляется к сроку:
  `доп. дни = остаток_дней × цена_старого / цена_нового`.
  Пример: осталось 20 дней START (99 000) → переход на PRO (399 000):
  30 + 20 × 99 000 / 399 000 ≈ 30 + 5 = **35 дней** PRO.
- **Тариф ниже**, пока текущий действует, — нельзя: 400 `PLAN_DOWNGRADE_WHILE_ACTIVE`.
  После окончания — можно.
- Тариф закончился — новый считается с момента оплаты.

### Права тарифа — `PLAN_FEATURE_REQUIRED`

Эндпоинт, которому нужен тариф выше текущего:

```json
HTTP 403
{
  "code": "PLAN_FEATURE_REQUIRED",
  "detail": "Доступно на тарифе BUSINESS и выше. Сейчас у вас FREE.",
  "feature": "statistics",
  "required_plan": "business",
  "current_plan": "free"
}
```

`feature`: `staff_access`, `statistics` (BUSINESS+), `branches`, `data_export` (PRO).
В кабинете сотрудника проверяется тариф **владельца** кабинета.

### Уведомления о тарифе

Тип уведомления `billing` (в `GET /notifications/`, WebSocket, Telegram, Web Push),
`payload.link` → `https://owner.rentoo.uz/billing`:
- «Тариф оплачен» / «Продвижение оплачено»;
- «Тариф заканчивается через 3 дня» и «Тариф заканчивается сегодня»;
- «Тариф закончился» — с числом снятых объявлений.

---

## 5. Заказы и оплата: Click, Payme, return URL

Оплата — разовым платежом: месяц тарифа или одно продвижение. Продление —
новый заказ. Режим оплаты задаёт сервер (`PAYMENTS_MODE`):

| Режим | Где | Что вернёт `POST /billing/orders/` |
|---|---|---|
| `live` | prod | 201, `status: "pending"`, `redirect_url` — страница оплаты Click или Payme |
| `stub` | dev/staging | 201, `status: "paid"`, `provider: "stub"` — оплачено сразу без денег, `redirect_url` = return URL |
| `off` | — | 503 `PAYMENT_METHOD_UNAVAILABLE` |

### `POST /billing/orders/` — оплатить тариф

Авторизация. Троттлинг 20/мин.

```json
{"kind": "plan", "plan": "start", "provider": "click"}
```

| Поле | Обяз. | Значения |
|---|---|---|
| `kind` | нет (по умолчанию `plan`) | `plan` \| `promotion` |
| `plan` | для `plan` | `start` \| `business` \| `pro` |
| `provider` | да | `click` \| `payme` |

Ответ `live`, Click:

```json
HTTP 201
{
  "id": 2, "kind": "plan", "plan": "pro", "promotion": "", "listing": null,
  "title": "Тариф PRO на 30 дней", "amount": "399000", "status": "pending",
  "provider": "click", "created_at": "2026-11-16T09:18:46.229542+05:00", "paid_at": null,
  "redirect_url": "https://my.click.uz/services/pay?service_id=11111&merchant_id=22222&amount=399000&transaction_param=2&return_url=https%3A%2F%2Fowner.rentoo.uz%2Fbilling%2Forders%2F2"
}
```

Ответ `live`, Payme — `redirect_url` вида `https://checkout.paycom.uz/<base64>`,
внутри `m=<merchant>;ac.order_id=3;a=39900000;c=https://owner.rentoo.uz/billing/orders/3`
(сумма в тийинах).

Ответ `stub`:

```json
HTTP 201
{"id": 1, "kind": "plan", "plan": "start", "promotion": "", "listing": null,
 "title": "Тариф START на 30 дней", "amount": "99000", "status": "paid", "provider": "stub",
 "created_at": "2026-11-16T09:18:46.216974+05:00", "paid_at": "2026-11-16T09:18:46.220019+05:00",
 "redirect_url": "https://owner.rentoo.uz/billing/orders/1"}
```

Ошибки:

| HTTP | code | Когда |
|---|---|---|
| 400 | `PLAN_DOWNGRADE_WHILE_ACTIVE` | тариф ниже действующего (`detail` с датой окончания) |
| 400 | `PLAN_NOT_FOR_SALE` | `free` или снятый с продажи |
| 400 | `validation_error` | нет `plan`, неизвестный `provider` и т. п. |
| 503 | `PAYMENT_METHOD_UNAVAILABLE` | онлайн-оплата выключена |

### Что делает фронт

1. `POST /billing/orders/` → открыть `redirect_url` (в той же вкладке или webview).
2. Пользователь платит у провайдера; провайдер сам сообщает серверу об оплате.
3. Провайдер возвращает пользователя на **return URL**:
   `https://owner.rentoo.uz/billing/orders/{id}` (шаблон `BILLING_RETURN_URL_TEMPLATE`).
4. Страница return URL опрашивает `GET /billing/orders/{id}/` (например, раз в 2–3 с, до минуты),
   пока `status` не станет `paid` или `cancelled`. Возврат на страницу **не** значит,
   что оплата прошла — смотреть только `status`.

### `GET /billing/orders/{id}/` — статус заказа

Авторизация, только свои (чужой — 404).

```json
{"id": 1, "kind": "plan", "plan": "start", "promotion": "", "listing": null,
 "title": "Тариф START на 30 дней", "amount": "99000", "status": "paid", "provider": "stub",
 "created_at": "2026-11-16T09:18:46.216974+05:00", "paid_at": "2026-11-16T09:18:46.220019+05:00"}
```

`status`: `pending` → `paid` | `cancelled`.

### `GET /billing/orders/` — мои заказы

Авторизация. Массив (последние 100, новые сверху) тех же объектов без `redirect_url`.

---

## 6. Продвижение: топ и VIP

### `GET /billing/promotions/` — цены и сроки

Без авторизации.

```json
[
  {"kind": "top", "name": "Поднять в топ", "price": 30000, "days": 7},
  {"kind": "vip", "name": "VIP", "price": 80000, "days": 30}
]
```

### `POST /billing/orders/` — купить продвижение

Тот же эндпоинт, что и для тарифа (оплата, return URL и режимы — как в §5).

```json
{"kind": "promotion", "promotion": "vip", "listing": 1, "provider": "payme"}
```

```json
HTTP 201
{"id": 4, "kind": "promotion", "plan": null, "promotion": "vip", "listing": 1,
 "title": "VIP: «Свадебные стулья»", "amount": "80000", "status": "pending", "provider": "payme",
 "created_at": "2026-11-16T09:18:46.245762+05:00", "paid_at": null,
 "redirect_url": "https://checkout.paycom.uz/..."}
```

- Только своё объявление со статусом `approved`.
- Повторная покупка того же вида продлевает срок от текущего окончания.
- После оплаты у объявления `is_vip`/`is_top: true` и `vip_until`/`top_until`.

| HTTP | code | Когда |
|---|---|---|
| 400 | `PROMOTION_REQUIRED` | нет `promotion` |
| 400 | `LISTING_NOT_FOUND` | объявления нет или оно чужое |
| 400 | `LISTING_NOT_PUBLISHED` | объявление не `approved` |
| 503 | `PAYMENT_METHOD_UNAVAILABLE` | онлайн-оплата выключена |

---

## 7. Показать номер

### `POST /listings/{id}/phone/`

Только авторизованным; объявление `approved`. Тела нет.

```json
HTTP 200
{"listing_id": 1, "owner_id": 1, "phone": "+998900000001", "name": "Прокат «Той»"}
```

`name` — название магазина или имя владельца (может быть пустым).

- Каждое нажатие записывается. В статистику владельца идёт первое нажатие
  пользователя по объявлению за 24 часа; нажатия владельца по своему — нет.
  На ответ это не влияет: номер возвращается всегда.
- Лимит на пользователя: **30 в час и 100 в сутки** (по всем объявлениям).

| HTTP | code | Когда |
|---|---|---|
| 401 | `not_authenticated` | без токена — показать вход |
| 404 | `not_found` | объявления нет или оно не опубликовано |
| 429 | `throttled` | лимит; `Retry-After` — через сколько секунд можно снова |

```json
HTTP 429
Retry-After: 3600
{"detail": "Запрос был проигнорирован. Expected available in 3600 seconds.", "code": "throttled"}
```

Номера в самом чате по-прежнему скрыты (они раскрывались только по сделке).

---

## 8. Жалобы

### `POST /listings/{id}/report/`

Только авторизованным; объявление `approved`. Лимит 20/час.

```json
{"reason": "fraud", "comment": "Просит предоплату на карту"}
```

`reason`: `fraud` (мошенничество), `prohibited` (запрещённая вещь), `wrong_info`
(неверные цена, фото или описание), `duplicate`, `unavailable` (уже не сдаётся),
`offensive`, `other`. `comment` — необязательно, до 1000 символов.

```json
HTTP 201
{"id": 1, "reason": "fraud", "comment": "Просит предоплату на карту", "status": "new",
 "created_at": "2026-11-16T09:18:46.275417+05:00"}
```

Повторная жалоба того же пользователя, пока первая не разобрана, — **200** с той же жалобой.

| HTTP | code | Когда |
|---|---|---|
| 400 | `own_listing` | жалоба на своё объявление |
| 400 | `validation_error` | неизвестная `reason` |
| 404 | `not_found` | объявления нет или не опубликовано |

---

## 9. Кабинет владельца `/api/v1/owner/`

### Чей кабинет и роли

Без заголовка — свой кабинет (роль `owner`). Сотрудник открывает кабинет
владельца заголовком **`X-Owner-Account: <id владельца>`** (или `?account=<id>`).

| Роль | Может |
|---|---|
| `owner` | всё |
| `manager` | всё, кроме управления сотрудниками |
| `viewer` | только чтение (GET) |

| HTTP | code | Когда |
|---|---|---|
| 403 | `NOT_STAFF` | не сотрудник этого владельца |
| 403 | `STAFF_ACCESS_SUSPENDED` | тариф владельца закончился или ниже BUSINESS — доступ приостановлен (сотрудник не удаляется) |
| 403 | `OWNER_ONLY` | действие только для владельца (сотрудники) |
| 403 | `READ_ONLY_ROLE` | `viewer` пытается изменить |

### `GET /owner/accounts/` — какие кабинеты мне доступны

Для переключателя кабинетов. Первый — свой.

```json
[
  {"id": 4, "name": "+998900000004", "role": "owner", "plan": "free"},
  {"id": 1, "name": "Прокат «Той»", "role": "manager", "plan": "business"}
]
```

### Брони

Бронь занимает `quantity` единиц объявления на каждый день с `start_date` по
`end_date` **включительно**, пока она `booked` или `issued`. Сделки (если флаг
включён) занимают по одной единице. Дни, закрытые владельцем вручную в
календаре объявления, недоступны целиком.

Статусы: `booked` → `issued` → `returned`; из `booked` и `issued` — `cancelled`.
Источник `source`: `rentoo` | `instagram` | `phone` (по умолчанию) | `other`.

#### `GET /owner/reservations/` — список, страницы

Фильтры: `from`, `to` (пересечение с периодом), `listing`, `status`, `branch`, `client`.
Порядок — по дате выдачи.

#### `POST /owner/reservations/` — новая бронь

```json
{
  "listing": 1, "quantity": 6, "start_date": "2026-11-17", "end_date": "2026-11-19",
  "source": "instagram", "client_name": "Дилноза", "client_phone": "+998901112233",
  "price": 120000, "notes": "Самовывоз"
}
```

Клиент: либо `client` (id из базы), либо `client_name` + `client_phone` —
тогда клиент находится по телефону или создаётся. Всё про клиента необязательно.

```json
HTTP 201
{
  "id": 1, "listing": 1, "listing_title": "Свадебные стулья", "quantity": 6,
  "start_date": "2026-11-17", "end_date": "2026-11-19", "source": "instagram",
  "status": "booked", "price": "120000", "notes": "Самовывоз",
  "client": 1, "client_info": {"id": 1, "name": "Дилноза", "phone": "+998901112233"},
  "created_by": 1, "created_at": "2026-11-16T09:18:46.284217+05:00", "updated_at": "2026-11-16T09:18:46.284219+05:00"
}
```

#### `GET | PATCH | DELETE /owner/reservations/{id}/`

`PATCH` — любые поля из POST и `status`. Даты, количество и объявление
проверяются заново (сама бронь в занятости не учитывается). `DELETE` — отмена
(`cancelled`), 204.

Ошибки броней:

| HTTP | code | Когда |
|---|---|---|
| 409 | `NOT_ENOUGH_STOCK` | на какой-то день не хватает единиц; `free` — сколько свободно на весь период |
| 400 | `INVALID_DATES` | возврат раньше выдачи, дольше 365 дней |
| 400 | `INVALID_STATUS` | недопустимый переход статуса |
| 400 | `validation_error` | чужое объявление или клиент, `quantity` < 1 |

```json
HTTP 409
{"code": "NOT_ENOUGH_STOCK", "detail": "На эти даты свободно 4 шт. из 10.", "free": 4}
```

```json
HTTP 400
{"code": "INVALID_STATUS", "detail": "Нельзя перевести бронь из «Забронировано» в «Возвращено»."}
```

Две одновременные брони на последние свободные единицы не пройдут обе:
вторая получит 409.

### Календарь и остатки

#### `GET /owner/listings/{id}/calendar/?from=&to=`

По умолчанию — 30 дней с сегодня; период до 92 дней. Брони — кроме отменённых.

```json
{
  "listing": 1, "title": "Свадебные стулья", "quantity": 10,
  "days": [
    {"date": "2026-11-16", "booked": 0, "free": 10, "blocked": false},
    {"date": "2026-11-17", "booked": 6, "free": 4, "blocked": false}
  ],
  "reservations": [{"id": 1, "quantity": 6, "start_date": "2026-11-17", "...": "..."}]
}
```

`blocked` — день закрыт владельцем вручную (`free: 0`).

#### `GET /owner/stock/?date=` или `?from=&to=` (+ `&branch=`)

Остатки по всем объявлениям аккаунта (кроме отклонённых). Без параметров — на
сегодня. На период: `booked` — по самому загруженному дню, `free` — сколько
можно отдать на весь период. Период до 366 дней.

```json
[{"id": 1, "title": "Свадебные стулья", "branch": null, "quantity": 10, "booked": 6, "free": 4}]
```

#### `GET /owner/listings/?branch=` — объявления аккаунта

```json
[{"id": 1, "title": "Свадебные стулья", "status": "approved", "quantity": 10,
  "price_per_day": "100000", "branch": null, "free_today": 10}]
```

#### `PATCH /owner/listings/{id}/` — привязать к точке (PRO)

`{"branch": 1}` или `{"branch": null}`. Привязка — тариф PRO (`PLAN_FEATURE_REQUIRED`),
отвязка — на любом. Чужая точка — 400.

Остальное в объявлении (название, цена, `quantity`, фото, статус) — как раньше,
`PATCH /listings/{id}/` от имени владельца. Сотрудник объявления не правит.

### Клиенты

#### `GET /owner/clients/?q=` — список, страницы

Поиск по имени и телефону.

```json
{"count": 1, "next": null, "previous": null, "results": [
  {"id": 1, "name": "Дилноза", "phone": "+998901112233", "notes": "", "rentoo_user_id": null,
   "reservations_count": 1, "last_reservation": "2026-11-17",
   "created_at": "2026-11-16T09:18:46.283375+05:00", "updated_at": "2026-11-16T09:18:46.283379+05:00"}
]}
```

`rentoo_user_id` — если номер совпал с пользователем Rentoo. `reservations_count` — без отменённых.

#### `POST /owner/clients/`

```json
{"name": "Шахло", "phone": "+998935554433", "notes": "Берёт на свадьбы"}
```

201 — объект клиента. Тот же телефон уже в базе — 400 `CLIENT_EXISTS`.

#### `GET | PATCH | DELETE /owner/clients/{id}/`

`GET` — карточка с историей аренд (`history` — брони клиента, новые сверху):

```json
{"id": 1, "name": "Дилноза", "phone": "+998901112233", "notes": "", "rentoo_user_id": null,
 "reservations_count": 1, "last_reservation": "2026-11-17", "created_at": "...", "updated_at": "...",
 "history": [{"id": 1, "listing": 1, "listing_title": "Свадебные стулья", "quantity": 6, "status": "issued", "...": "..."}]}
```

`PATCH` — `name`, `phone`, `notes`. `DELETE` — удаляет клиента, брони остаются без клиента.

### Сотрудники (BUSINESS+, только владелец)

#### `GET /owner/staff/` — массив

```json
[{"id": 1, "user_id": 4, "user_phone": "+998900000004", "name": "", "role": "manager",
  "created_at": "2026-11-16T09:18:46.311558+05:00"}]
```

#### `POST /owner/staff/`

```json
{"phone": "+998900000004", "role": "manager"}
```

Номер должен принадлежать пользователю Rentoo (иначе 400 `phone` — «пусть
сначала войдёт в Rentoo»). `role`: `manager` | `viewer` (по умолчанию `manager`).

| HTTP | code | Когда |
|---|---|---|
| 403 | `PLAN_FEATURE_REQUIRED` | тариф ниже BUSINESS (`feature: staff_access`) |
| 400 | `STAFF_SELF` | свой номер |
| 400 | `STAFF_EXISTS` | уже сотрудник |
| 403 | `OWNER_ONLY` | вызывает сотрудник |

#### `PATCH | DELETE /owner/staff/{id}/`

`PATCH {"role": "viewer"}`; `DELETE` — 204.

### Точки (филиалы, PRO)

#### `GET /owner/branches/` — массив; `POST /owner/branches/`

```json
{"name": "Чиланзар", "address": "Чиланзар 9", "phone": "+998712000000"}
```

```json
HTTP 201
{"id": 1, "name": "Чиланзар", "address": "Чиланзар 9", "phone": "+998712000000",
 "is_active": true, "listings_count": 0, "created_at": "2026-11-16T09:18:46.315006+05:00"}
```

Создание и правка — PRO (`feature: branches`); просмотр — на любом тарифе.

#### `GET | PATCH | DELETE /owner/branches/{id}/`

При удалении объявления точки остаются без привязки.

### Статистика (BUSINESS+)

#### `GET /owner/stats/?month=YYYY-MM`

По умолчанию — текущий месяц. Объявления аккаунта, кроме отклонённых.

```json
{
  "month": "2026-11",
  "totals": {"views": 1, "phone_reveals": 1, "chat_messages": 1, "listings": 1},
  "listings": [{"id": 1, "title": "Свадебные стулья", "status": "approved",
                "views": 1, "phone_reveals": 1, "chat_messages": 1}],
  "by_month": [
    {"month": "2026-06", "views": 0, "phone_reveals": 0, "chat_messages": 0},
    {"month": "2026-11", "views": 1, "phone_reveals": 1, "chat_messages": 1}
  ]
}
```

- `views` — открытия карточки за месяц;
- `phone_reveals` — «Показать номер» без повторов одного человека за 24 ч и без владельца;
- `chat_messages` — сообщения арендаторов в диалогах по объявлению (ответы владельца не считаются);
- `by_month` — 6 месяцев, от старого к выбранному.

Ошибки: 403 `PLAN_FEATURE_REQUIRED`, 400 `INVALID_DATES` (неверный `month`).

### Выгрузка (PRO)

#### `GET /owner/export/{listings|reservations|clients}/?type=csv|xlsx`

По умолчанию `xlsx`. Ответ — файл, `Content-Disposition: attachment; filename="rentoo-reservations-2026-11-16.xlsx"`.
CSV — UTF-8 с BOM (Excel открывает кириллицу). Параметр называется `type`, не
`format` (`format` занят DRF).

Колонки:
- `listings`: ID, Название, Статус, Количество, Цена за сутки, Залог, Точка, Город, Создано;
- `reservations`: ID, Объявление, Количество, Выдача, Возврат, Статус, Источник, Клиент, Телефон, Сумма, Заметки;
- `clients`: ID, Имя, Телефон, Заметки, Броней, Добавлен.

Ошибки: 403 `PLAN_FEATURE_REQUIRED` (`feature: data_export`), 400 `INVALID_FORMAT`, 404 — неизвестная выгрузка.

### Напоминания о выдаче и возврате

Каждое утро (08:00) владельцу и менеджерам кабинета приходит уведомление типа
**`crm`**: «Сегодня выдача» (бронь `booked` с выдачей сегодня) и «Сегодня
возврат» (`booked`/`issued` с возвратом сегодня). `payload`:
`{title, message, link: "https://owner.rentoo.uz/reservations/{id}", reservation_id}`.
SMS клиентам не отправляются.

---

## 10. Модерация (сотрудники)

Все — только `is_staff` (иначе 403 `permission_denied`).

### `GET /admin-api/moderation/queue/` — очередь, страницы

Объявления на модерации и объявления с открытыми жалобами; больше жалоб — выше.

```json
{"count": 1, "next": null, "previous": null, "results": [
  {"id": 1, "title": "Свадебные стулья", "status": "approved", "owner_id": 1,
   "owner_phone": "+998900000001", "open_reports": 1, "waiting_since": "2026-11-16T09:18:46.275417+05:00"}
]}
```

### `GET /admin-api/moderation/reports/?status=new&listing=` — жалобы, страницы

```json
{"id": 1, "listing": 1, "listing_title": "Свадебные стулья", "listing_status": "approved",
 "reporter_phone": "+998900000002", "reason": "fraud", "comment": "Просит предоплату на карту",
 "status": "new", "resolution": "", "resolved_by": null, "resolved_at": null,
 "created_at": "2026-11-16T09:18:46.275417+05:00"}
```

Статусы жалобы: `new`, `dismissed` (отклонена), `action_taken` (объявление скрыто).

### `POST /admin-api/moderation/reports/{id}/resolve/`

```json
{"action": "dismiss", "comment": "Проверили, всё честно"}
```

`action`: `dismiss` — отклонить жалобу; `hide` — скрыть объявление (закрывает
**все** открытые жалобы на него, `comment` уходит владельцу как причина).
Ответ — жалоба после решения.

### `POST /admin-api/moderation/listings/{id}/hide/` — скрыть

`{"reason": "Запрещённая вещь"}` → `{"id": 1, "status": "blocked"}`. Владелец получает уведомление с причиной.

### `DELETE /admin-api/moderation/listings/{id}/hide/` — вернуть

→ `{"id": 1, "status": "approved"}`.

Одобрить или отклонить объявление на модерации — как раньше:
`POST /listings/{id}/moderate/` `{"status": "approved" | "rejected", "rejection_reason"}`.

---

## 11. Админка тарифов (сотрудники)

Только `is_staff`.

### `GET /admin-api/billing/subscriptions/?plan=&state=active|expired&q=<телефон>` — страницы

```json
{"id": 1, "user_id": 1, "phone": "+998900000001", "plan": "pro",
 "ends_at": "2026-12-23T19:57:33.258602+05:00", "is_active": true, "paid_total": "399000",
 "created_at": "2026-11-16T09:18:46.221115+05:00"}
```

`paid_total` — сумма оплаченных тарифов пользователя (без заглушки).

### `GET /admin-api/billing/orders/?status=&kind=&provider=&needs_attention=1&q=` — страницы

```json
{"id": 4, "user_id": 1, "phone": "+998900000001", "kind": "promotion", "plan": null,
 "promotion": "vip", "listing": 1, "amount": "80000", "provider": "payme", "status": "paid",
 "provider_transaction_id": "6748a1...", "needs_attention": "", "created_at": "...", "paid_at": "..."}
```

`needs_attention` не пустой — деньги пришли, но заказ не применился (например,
тариф ниже уже действующего); решает сотрудник.

### `POST /admin-api/billing/subscriptions/extend/` — ручное продление

```json
{"phone": "+998900000002", "plan": "business", "days": 30, "comment": "Оплата наличными"}
```

`user` (id) или `phone`; `days` — 1…366, по умолчанию 30. Тот же тариф — с
конца периода; другой (выше или ниже) — сразу (для тарифа выше остаток
пересчитывается, как при оплате). В истории — «вручную» и кто продлил. Снятые
по тарифу объявления возвращаются. Ответ — строка подписки, как в списке.

### `GET /admin-api/billing/metrics/?days=30`

```json
{
  "paying_total": 2,
  "paying_by_plan": {"start": 0, "business": 1, "pro": 1},
  "mrr": 598000,
  "churn": {"days": 30, "paying_at_start": 0, "churned": 0, "rate": 0.0},
  "revenue": {"days": 30, "total": 0, "plans": 0, "promotions": 0},
  "new_paying": 2,
  "expiring_7d": 0
}
```

- `mrr` — сумма месячных цен действующих платных тарифов (включая выданные вручную);
- `churn` — у скольких платный тариф действовал `days` дней назад и не действует сейчас; `rate` — доля;
- `revenue` — оплаченные заказы за период без заглушки, по тарифам и продвижению;
- `new_paying` — впервые перешли на платный тариф за период;
- `expiring_7d` — тарифы, которые закончатся в ближайшие 7 дней.

---

## 12. Обработчики Click и Payme (для провайдеров)

Фронт их не вызывает. Работают только при `PAYMENTS_MODE=live` (иначе 404).
Отдельны от вебхуков сделки. Должны быть доступны без Basic Auth nginx.

| Провайдер | URL | Протокол |
|---|---|---|
| Payme | `POST https://back.rentoo.uz/api/v1/billing/payme/` | Merchant API, JSON-RPC 2.0; Basic `Paycom:<ключ кассы>`; ответ всегда HTTP 200 |
| Click | `POST https://back.rentoo.uz/api/v1/billing/click/prepare/` и `.../click/complete/` | SHOP API, form-urlencoded, подпись md5 |

**Payme:** поле счёта кассы — **`order_id`** (id заказа), сумма — в тийинах.
Методы: CheckPerformTransaction, CreateTransaction, PerformTransaction,
CancelTransaction, CheckTransaction, GetStatement. Одна транзакция на заказ
(вторая — -31052). Транзакция, не проведённая за 12 часов, отменяется (reason 4).
Проведённую отменить нельзя (-31007): тариф или продвижение уже выданы.
Коды: -32504 авторизация, -31001 сумма, -31003 нет транзакции, -31008 нельзя
выполнить, -31050 нет заказа, -31051 заказ нельзя оплатить, -31052 заказ уже оплачивается.

**Click:** `merchant_trans_id` = id заказа, сумма — в сумах. Prepare отдаёт
`merchant_prepare_id` = id заказа; Complete с ошибкой Click (`error` < 0)
отменяет заказ. Повторный Complete оплаченного — -4. Коды: 0 успех, -1
подпись, -2 сумма, -3 action, -4 уже оплачен, -5 нет заказа, -6 нет
транзакции, -8 ошибка запроса, -9 отменён / нельзя оплатить.

---

## 13. Все коды ошибок

| code | HTTP | Где |
|---|---|---|
| `DEAL_FLOW_DISABLED` | 410 | эндпоинты сделки и торга (§3) |
| `LIMIT_REACHED` | 400 | создание и активация объявления (§2); поля `plan`, `limit`, `active` |
| `PLAN_FEATURE_REQUIRED` | 403 | права тарифа (§4); поля `feature`, `required_plan`, `current_plan` |
| `PLAN_DOWNGRADE_WHILE_ACTIVE` | 400 | покупка тарифа ниже действующего |
| `PLAN_NOT_FOR_SALE` | 400 | покупка `free` или снятого тарифа |
| `PAYMENT_METHOD_UNAVAILABLE` | 503 | онлайн-оплата выключена |
| `PROMOTION_REQUIRED` | 400 | заказ продвижения без вида |
| `LISTING_NOT_FOUND` | 400 | продвижение чужого или несуществующего объявления |
| `LISTING_NOT_PUBLISHED` | 400 | продвижение неопубликованного |
| `NOT_ENOUGH_STOCK` | 409 | бронь в кабинете; поле `free` |
| `INVALID_DATES` | 400 | даты брони, периода календаря/остатков, `month` |
| `INVALID_STATUS` | 400 | переход статуса брони |
| `INVALID_FORMAT` | 400 | `type` выгрузки |
| `CLIENT_EXISTS` | 400 | клиент с этим телефоном уже есть |
| `STAFF_SELF`, `STAFF_EXISTS` | 400 | добавление сотрудника |
| `NOT_STAFF` | 403 | чужой кабинет |
| `STAFF_ACCESS_SUSPENDED` | 403 | тариф владельца не включает сотрудников |
| `OWNER_ONLY` | 403 | управление сотрудниками сотрудником |
| `READ_ONLY_ROLE` | 403 | `viewer` пытается изменить |
| `own_listing` | 400 | жалоба на своё объявление |
| `throttled` | 429 | «Показать номер» (30/час, 100/сутки), жалобы (20/час), заказы (20/мин); `Retry-After` |
| `not_authenticated` | 401 | нет токена |
| `not_found` | 404 | нет объекта или он чужой |
| `validation_error` | 400 | ошибки полей: `{"<поле>": ["..."]}` |
