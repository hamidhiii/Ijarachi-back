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
  после коммита): аренда минус комиссия — в кошелёк владельцу, залог целиком —
  в кошелёк арендатору.
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
Telegram-бот (SMS Eskiz — запасной путь). Номер привязывается к чату, когда
пользователь делится контактом **с кнопки бота**: контакт принимается только
если `contact.user_id == from.id`. Контакт из записной книжки (без `user_id`)
или чужой — отказ, без привязки и без кода
([apps/users/views/telegram.py](apps/users/views/telegram.py)).

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
- Даты брони в прошлом не запрещены; `min_rental_days` не проверяется.
- Телефоны участников видны в чате до оплаты (`sender_phone`, `participant_phones`).
- Сигнал создания профиля в `UsersConfig.ready` регистрируется со слабой
  ссылкой и не срабатывает; профиль создаётся явно при входе по OTP.
