# Rentoo / Ijarachi — карта бэкенда

P2P-аренда вещей в Узбекистане (MVP — «Той и праздники»). Django 4.2 + DRF,
PostgreSQL, Redis, Celery/Beat, Channels (WebSocket), JWT. Фронт — отдельный
репозиторий Ijarachi-front (там свой `PROJECT_OVERVIEW.md`), мобильное
приложение — Ijarachi-mobile. История изменений — [CHANGELOG.md](CHANGELOG.md).

## Оглавление
1. [Запуск и окружения](#1-запуск-и-окружения)
2. [Карта репозитория](#2-карта-репозитория)
3. [Сделка: статусы и даты](#3-сделка-статусы-и-даты)
4. [Оплата](#4-оплата)
5. [Залог и кошелёк](#5-залог-и-кошелёк)
6. [Вход и Telegram-бот](#6-вход-и-telegram-бот)
6b. [Частное лицо и магазин](#6b-частное-лицо-и-магазин)
7. [Проверка личности (KYC, MyID)](#7-проверка-личности-kyc-myid)
8. [Тесты](#8-тесты)
9. [Известные пробелы](#9-известные-пробелы)

## 1. Запуск и окружения

Docker: `cp .env.example .env && docker compose up -d --build` (миграции и
категории накатывает сервис `migrate`). Все переменные — в [.env.example](.env.example).

Окружение задаёт `APP_ENV` (`dev` | `staging` | `prod`; без значения: `DEBUG=True`
→ dev, иначе prod). От него зависят заглушки, см. [core/runtime_modes.py](core/runtime_modes.py):

| Настройка | off | stub | live |
|---|---|---|---|
| `PAYMENTS_MODE` | только наличные, вебхуки 404 | оплата подтверждается сразу, без денег | Click/Payme + вебхуки |
| `MYID_MODE` | заглушки нет | `POST /kyc/myid/stub/verify/` помечает профиль проверенным | не поддерживается |

Заглушки разрешены только в `staging` и в `dev` при `DEBUG=True`. В `prod` со
`stub` сервер, воркер и `manage.py` **не стартуют** (`ImproperlyConfigured` из
`PaymentsConfig.ready`), а сами заглушки ещё раз проверяют режим в момент
подтверждения. Умолчание `PAYMENTS_MODE`: stub там, где можно, иначе off.
Так же в `prod` сервер не стартует без своего `SECRET_KEY` (ключ по умолчанию
лежит в репозитории, им подписываются JWT). Порт 8000 в docker-compose открыт
только на `127.0.0.1` — снаружи приложение доступно лишь через nginx.

### Доска объявлений и выключенная сделка

С 16.11.2026 Rentoo — доска объявлений аренды с платными тарифами для прокатов.
Сделка через платформу (разделы 3–5: бронь и оплата, эскроу, залог, кошелёк,
споры, торг, комиссия, отзывы по сделке) выключена флагом `DEAL_FLOW_ENABLED`
(по умолчанию `False`, [core/feature_flags.py](core/feature_flags.py)), но не
удалена: модели, данные и код на месте, флаг возвращает всё без миграций.

При выключенном флаге эндпоинты `deals/*`, `bookings/*`, `my-rentals/`,
`pricing/payout/`, `offers/*` и старые вебхуки оплаты сделки отвечают **410**
`{"code": "DEAL_FLOW_DISABLED"}` — раньше проверки прав, так что аноним тоже
получает 410, а не 401. Задачи Celery по сделкам (`expire_stale_bookings`,
`notify_expiring_bookings`, `release_escrow`, уведомления о сделке, расход KYC)
выходят, ничего не делая. Отзывы читаются как раньше.

## 2. Карта репозитория

| Путь | Что там |
|---|---|
| [core/settings.py](core/settings.py) | все настройки, читаются из `.env` через decouple |
| [core/runtime_modes.py](core/runtime_modes.py) | где разрешены заглушки, проверка при старте |
| [core/settings_test.py](core/settings_test.py) | настройки тестов (кэш/каналы/Celery в памяти) |
| [core/views.py](core/views.py) | админ-API: дашборд, выгрузка финансов, блокировка пользователей |
| [apps/users](apps/users) | пользователь, профиль, OTP-вход, Telegram-бот, KYC, заглушка MyID |
| [apps/catalog](apps/catalog) | категории, объявления, фото, избранное, торг (Offer), ручной календарь |
| [apps/bookings](apps/bookings) | сделки, занятость дат, фотопротокол, споры, отзывы, расчёт и залог |
| [apps/payments](apps/payments) | платежи, провайдеры оплаты, вебхуки Click/Payme, кошелёк |
| [apps/chat](apps/chat) | диалоги и сообщения (REST + WebSocket) |
| [apps/notifications](apps/notifications) | уведомления: WebSocket, Telegram, Web Push |
| [apps/monitoring](apps/monitoring) | `/monitor/` — панель сотрудников (сделки, споры, платежи, ошибки) |

## 3. Сделка: статусы и даты

Статусы ([apps/bookings/models.py](apps/bookings/models.py)): `draft → pending_payment
→ paid → in_progress → returned → completed`, плюс `cancelled` и `disputed`.
Переходы и кто их делает — `BookingStatusUpdateSerializer.ALLOWED_TRANSITIONS`
и описание `PATCH /deals/{id}/status/` в Swagger.

**Цена** — `compute_pricing` в [apps/bookings/serializers.py](apps/bookings/serializers.py),
модель B: арендатор платит цену владельца × дни + залог; комиссия
`PLATFORM_COMMISSION_PERCENT` (15 %) удерживается из выплаты владельцу и
фиксируется в сделке (`commission_amount`). Если у арендатора есть принятое
предложение цены (`Offer`, последняя строка ветки — accepted), сделка считается
от согласованной цены и ссылается на него (`Booking.offer`). Подсказка «вы
получите X» для формы объявления — `GET /api/v1/pricing/payout/?price_per_day=&days=`.
Даты брони: начало не в прошлом, не короче `min_rental_days` объявления.

**Торг** ([apps/catalog/views.py](apps/catalog/views.py)): сумма > 0; в ветке
(объявление, арендатор) одна ставка без ответа — новая до ответа даёт 400
`offer_pending_exists`.

**Модерация**: правка у одобренного объявления названия, описания, категории,
характеристик или адреса, а также новое фото возвращают его в `pending`
(цену и залог можно менять без модерации). Правки сотрудника — без.

**Занятость дат** — [apps/bookings/availability.py](apps/bookings/availability.py).
Даты занимает сама бронь, пока она в `pending_payment`, `paid` или `in_progress`.
Черновик даты не занимает. Отмена или истечение выводят бронь из этих статусов
и освобождают ровно её дни. `ItemAvailability.blocked_dates` хранит только дни,
закрытые владельцем вручную; `GET /listings/{id}/availability/` отдаёт их
объединение с бронями (`blocked_dates`) и разбивку (`manual_blocked_dates`,
`booked_dates`). PATCH календаря меняет только ручные дни.

Гонку двух броней на одни даты разводит `lock_item`: проверка пересечения и
перевод брони в занимающий статус идут в одной транзакции под
`select_for_update` строки объявления (создание черновика, `POST /deals/{id}/pay/`,
старый `/bookings/create/`). Аренда не длиннее `BOOKING_MAX_DAYS` (365).

Неоплаченные заявки старше `BOOKING_ABANDON_TIMEOUT_HOURS` отменяет задача
`expire_stale_bookings` (Celery Beat, раз в час).

## 4. Оплата

`POST /deals/{id}/pay/` с `{"provider": "click" | "payme" | "cash"}` выбирает
провайдера через [apps/payments/providers.py](apps/payments/providers.py):

- `cash` — всегда; эскроу и залог через платформу не идут, бронь из ожидания
  выводит владелец (`pending_payment → confirmed`). **Подтвердить бронь вручную
  владелец может только при оплате наличными** — по последнему выбранному способу.
- `click` / `payme` при `live` — ссылка на чекаут, оплату подтверждает вебхук.
- `click` / `payme` при `stub` — `StubProvider`: платёж с `provider=stub` сразу
  `paid`, `redirect_url` ведёт на страницу сделки. В GMV дашборда не входит.
- при `off` — 503 `PAYMENT_METHOD_UNAVAILABLE`.

Повторный вызов pay для той же сделки разрешён (сменить способ, новая ссылка);
прежние незавершённые попытки помечаются `failed`. Подтверждение оплаты —
`apps/payments/services.finalize_paid_payment`: сделка `paid`, эскроу `held`,
залог `held`, раскрываются контакты, открывается чат. Оплата, пришедшая за уже
отменённую сделку, сделку не воскрешает — пишется ошибка для ручного возврата.

Вебхуки `/api/v1/payments/{payme,click}/{webhook,callback}/` отвечают 404 везде,
кроме `PAYMENTS_MODE=live`. Сами интеграции Click/Payme ещё не доведены (см. §9).

## 5. Залог и кошелёк

Залог учитывается отдельно от аренды: `Booking.deposit_status` (`none`,
`pending`, `held`, `refunded`, `partially_withheld`, `withheld`) и история
`DepositOperation` (`hold`, `refund`, `withhold` — сумма, кто решил, комментарий).
Оба видны в карточке сделки (`deposit_status`, `deposit_operations`).

Расчёт — [apps/bookings/settlement.py](apps/bookings/settlement.py):

- **Сделка завершена** (`returned → completed` владельцем, задача `release_escrow`
  после коммита): аренда минус комиссия, зафиксированная в сделке, — в кошелёк
  владельцу, залог целиком — в кошелёк арендатору.
- **Спор** закрывает сотрудник: `POST /deals/{id}/resolve-dispute/`
  `{"deposit_withheld": <сум>, "comment": ""}`. Удержанная часть залога —
  владельцу, остаток — арендатору, сделка — `completed`.
- **Отмена оплаченной сделки** — залог возвращается вместе со всей оплатой
  (`Transaction` типа refund), в кошелёк не зачисляется.

Кошелёк — `Profile.wallet_balance`, меняется **только** через
[apps/payments/wallet.credit_wallet](apps/payments/wallet.py): профиль под
`select_for_update`, прибавление через `F()`, рядом строка `WalletTransaction`
(тип, сумма, сделка, баланс после, дата). Профили обеих сторон блокируются в
порядке id (без взаимных блокировок). Повторный или параллельный расчёт сделки
ничего не начисляет второй раз: сделка под `select_for_update`, после расчёта
`escrow_status=released`, плюс уникальное ограничение «одно начисление каждого
типа на сделку». В админке баланс и журнал только для чтения.

## 6. Вход и Telegram-бот

Вход по OTP (`/auth/send-otp/`, `/auth/verify-otp/`), коды доставляет
Telegram-бот (SMS Eskiz — запасной путь). Код генерируется через `secrets`; после
`OTP_MAX_ATTEMPTS` (5) неверных вводов все живые коды номера гаснут
(`otp_attempts_exceeded`, нужен новый) — общий хелпер `apps/users/otp.check_code`,
он же для смены телефона.

**Блокировка** (`PATCH /admin-api/users/{id}/status/`): заблокированный получает
403 `user_blocked` на входе по OTP, его refresh-токены отзываются, обновление
токена отказывает (`ActiveUserTokenRefreshSerializer`), WebSocket не подключается. Номер привязывается к чату, когда
пользователь делится контактом **с кнопки бота**: контакт принимается только
если `contact.user_id == from.id`. Контакт из записной книжки (без `user_id`)
или чужой — отказ, без привязки и без кода
([apps/users/views/telegram.py](apps/users/views/telegram.py)).

## 6a. Чат и уведомления

Номера сторон (`sender_phone`, `participant_phones`) в чате видны только в
диалоге по сделке с раскрытыми контактами (`contact_revealed_at` — после оплаты
или принятия брони за наличные); свой номер — всегда. То же в WebSocket.

Web Push: `endpoint` подписки — только HTTPS к push-сервисам из
`WEB_PUSH_ALLOWED_HOSTS` (FCM, Mozilla, Apple, Windows), иначе 400; старые
подписки на чужие адреса задача рассылки удаляет, не обращаясь к ним (SSRF).

## 6b. Частное лицо и магазин

`Profile.account_type`: `private` (по умолчанию) или `shop` — переключает сам
пользователь в `PATCH /api/v1/profile/`. Магазину нужно непустое `shop_name`,
иначе 400 `shop_name_required` (и при переключении, и при стирании названия).

Что даёт магазин (лимит объявлений с 16.11.2026 задаёт тариф, см. §6c):
- **Бейдж и часы работы:** `owner.account_type` в карточках объявлений,
  `account_type` и `working_hours` в `GET /users/{id}/` (часы — только у магазина).
- **Сводная статистика:** `GET /api/v1/listings/my/stats/` — просмотры,
  избранное, заявки и оплаченные сделки по каждому объявлению и в сумме; частнику
  403 `shop_only`.

Миграция `users.0009` сделала магазинами тех, у кого объявлений в работе больше
частного лимита (демо-аккаунт), — названия им не придумывались.

## 6c. Тарифы и лимит объявлений

Приложение [apps/billing](apps/billing). `Plan` — справочник тарифов (строки
создаёт миграция `billing.0002`, цены и права правятся в админке):

| Тариф | Цена/мес | Активных объявлений | Права |
|---|---|---|---|
| FREE | 0 | 10 | — |
| START | 99 000 | 100 | — |
| BUSINESS | 199 000 | 300 | приоритет в выдаче, сотрудники, статистика |
| PRO | 399 000 | без лимита | всё BUSINESS + филиалы, выгрузка CSV/XLSX |

`Subscription` — одна строка на пользователя: тариф действует, пока `ends_at` в
будущем, иначе пользователь на FREE (`apps.billing.plans.current_plan`).
`SubscriptionPeriod` — история периодов (оплата или вручную). Менять тариф —
только `apps.billing.services.extend_subscription`: тот же тариф продлевается с
конца текущего периода, тариф выше начинается сразу (остаток не переносится),
тариф ниже, пока текущий действует, — 400 `PLAN_DOWNGRADE_WHILE_ACTIVE`.
Период — `BILLING_PERIOD_DAYS` (30).

**Оплата** — разовым платежом за период, продление вручную (новый заказ):
`POST /api/v1/billing/orders/` `{"kind": "plan", "plan": "start", "provider": "click" | "payme"}`
→ 201 с `redirect_url` на чекаут. Режимы те же, что у сделки (`PAYMENTS_MODE`):
`live` — Click/Payme, `stub` (dev/staging) — заказ сразу оплачен, `off` — 503
`PAYMENT_METHOD_UNAVAILABLE`. Заказ — `BillingOrder` (тариф или продвижение),
применяет его `services.mark_order_paid` ровно один раз (заказ под блокировкой).
Остальное: `GET /billing/plans/` (публично), `GET /billing/subscription/`
(тариф, срок, `days_left`, лимит, `paused_listings`), `GET /billing/orders/[{id}/]`.

Обработчики провайдеров (только `PAYMENTS_MODE=live`, иначе 404), отдельно от
вебхуков сделки:
- **Payme** `POST /api/v1/billing/payme/` — [apps/billing/payme.py](apps/billing/payme.py):
  CheckPerformTransaction, CreateTransaction, PerformTransaction,
  CancelTransaction, CheckTransaction, GetStatement. Счёт `account.order_id`,
  сумма в тийинах, ответ всегда HTTP 200, Basic `Paycom:<PAYME_SECRET_KEY>`.
  Одна транзакция на заказ (вторая — -31052), не проведённая за 12 ч
  отменяется (reason 4), проведённую не отменяем (-31007: услуга выдана).
- **Click** `POST /api/v1/billing/click/prepare/` и `/complete/` —
  [apps/billing/click.py](apps/billing/click.py): `merchant_trans_id` = id заказа,
  сумма в сумах, подпись md5 (у Complete с `merchant_prepare_id`); повторный
  Complete — «уже оплачен» (-4), ошибка Click в Complete отменяет заказ (-9).

Перед списанием (Check/Create, Prepare) заказ проверяется ещё раз: не отменён,
тариф всё ещё можно купить. Если тариф ниже действующего всё же оплатили (две
вкладки), деньги приняты, а заказ помечен `needs_attention` для сотрудника.

**Окончание тарифа** — задача `expire_subscriptions` (Beat, каждый час): тариф
истёк → FREE; активные объявления сверх лимита уходят в `inactive` с пометкой
`plan_paused_status` (остаются VIP, топ, затем самые свежие), ничего не
удаляется. После новой оплаты такие объявления возвращаются в прежний статус
сами, сколько позволяет лимит; если владелец сам менял статус — не трогаем.
**Напоминания** — `remind_subscriptions` (Beat, 10:00): за 3 дня и в последний
день по местной дате; уведомление типа `billing` (WebSocket, Telegram, Web Push)
со ссылкой на `OWNER_FRONTEND_BASE_URL/billing`. Обе задачи идемпотентны.

**Продвижение** ([apps/billing/promotions.py](apps/billing/promotions.py)):
«Поднять в топ» — `PROMO_TOP_PRICE` 30 000 сум на `PROMO_TOP_DAYS` 7 дней, VIP —
`PROMO_VIP_PRICE` 80 000 на `PROMO_VIP_DAYS` 30 дней. Покупка — тот же заказ:
`POST /billing/orders/` `{"kind": "promotion", "promotion": "top" | "vip", "listing": <id>, "provider": …}`,
только своё опубликованное объявление (`LISTING_NOT_FOUND`, `LISTING_NOT_PUBLISHED`).
Повторная покупка продлевает от текущего окончания. Действующее состояние —
`Item.top_until` / `vip_until` (в карточке `is_top`, `is_vip`), история —
`Promotion`. Цены и сроки — `GET /billing/promotions/`.

**Порядок выдачи** `GET /listings/` по умолчанию —
[apps/catalog/ranking.py](apps/catalog/ranking.py): VIP > топ > владелец на
тарифе с приоритетом (BUSINESS/PRO, пока тариф действует) > дата. Явная
сортировка (`ordering=price`, `-price`, `date`, `relevance`, поля
OrderingFilter) работает как раньше.

**Права тарифа** — `apps.billing.plans.require_feature(user, 'statistics' | 'staff_access' | 'branches' | 'data_export')`:
403 `{"code": "PLAN_FEATURE_REQUIRED", "feature", "required_plan", "current_plan"}`.

**Лимит активных объявлений** (`pending` + `approved`) —
[apps/catalog/limits.py](apps/catalog/limits.py), при создании и при активации
(снятое/отклонённое → на модерацию), под `select_for_update` пользователя.
Сверх лимита — 400 `{"code": "LIMIT_REACHED", "detail", "plan", "limit", "active"}`.
Профиль отдаёт `listing_limit` (null — без лимита) и `live_listings`.

**Количество:** `Item.quantity` (≥ 1) — объявление описывает модель вещи, у
проката их может быть 40 одинаковых; меняется без повторной модерации.

## 7. Проверка личности (KYC, MyID)

Собственный KYC (OCR паспорта + сверка лица) выключен `KYC_ENABLED=False`:
эндпоинты не регистрируются, сделки не требуют проверки. Интеграции с MyID нет;
для сценариев с проверкой есть заглушка `POST /api/v1/kyc/myid/stub/verify/`
(только `MYID_MODE=stub` в dev/staging, иначе 404).

## 8. Тесты

Нужен PostgreSQL (тесты гонок опираются на `select_for_update`), Redis — нет:

```bash
python manage.py test --settings=core.settings_test
```

Тесты гонок (`TransactionTestCase` + потоки): двойная бронь одних дат,
параллельные начисления в кошелёк, параллельный расчёт одной сделки. Проверка
«stub в prod не стартует» запускает настоящий `manage.py check` в подпроцессе.

## 9. Известные пробелы

- Интеграции Click/Payme не доведены: вебхуки не сверяют сумму и статус
  сделки, подпись Complete у Click без `merchant_prepare_id`, ответы Payme не
  по спецификации. Поэтому `live` пока включать нельзя.
- Кошелёк — внутренний учёт: вывода денег на карту нет.
- Номер телефона в тексте сообщения или описании не фильтруется — только поля API.
- N+1 в списке объявлений (рейтинг, отзывы, избранное — по запросу на строку)
  и тяжёлый список диалогов.
