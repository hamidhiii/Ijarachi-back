# SYNTH Share - P2P Rental Platform (Backend)

Профессиональная Backend-часть для платформы шеринга (P2P аренды вещей), сфокусированной на Узбекистане. Проект полностью поддерживает мультиязычность, real-time чаты и безопасные платежи.

## 🚀 Технологический стек

- **Язык**: Python 3.11+
- **Фреймворк**: Django 4.2+, Django REST Framework (DRF)
- **WebSockets**: Django Channels + Daphne (Real-time чаты)
- **База Данных**: PostgreSQL
- **Брокер/Кэш**: Redis
- **Фоновые задачи**: Celery + Celery Beat
- **Авторизация**: JWT (SimpleJWT)
- **Контейнеризация**: Docker (Multi-stage build)
- **i18n**: RU, UZ (Latin), EN (поддержка заголовка `Accept-Language`)
- **Платежи**: Payme (JSON-RPC), Click (SHOP API)

---

## 🏗 Архитектура модулей (Apps)

1. **`users`** — Кастомная модель пользователя (телефон как логин), OTP-авторизация, KYC-верификация (документы), управление FCM-токенами для Push-уведомлений.
2. **`catalog`** — Древовидные категории (MPTT), объявления с геопозицией, управление доступностью вещей (блокировка дат).
3. **`bookings`** — Основная бизнес-логика сделок, статусная машина, защита от двойного бронирования (SELECT FOR UPDATE).
4. **`payments`** — Эскроу-сервис, холдирование средств через Payme/Click до успешного завершения аренды.
5. **`chat`** — Real-time общение через WebSockets. Поддержка JWT-аутентификации в WebSocket-соединении.
6. **`favorites`** — Система «Избранного» для сохранения объявлений пользователями.
7. **`reviews`** — Двусторонняя система отзывов и автоматический пересчет рейтинга профилей.

---

## 🛠 Установка и Запуск

### Запуск через Docker (Рекомендуемый)

Проект использует оптимизированную многоэтапную сборку и Daphne в качестве ASGI-сервера.

1. Подготовьте `.env` на основе `.env.example`.
2. Запустите стек:
   ```bash
   docker-compose up -d --build
   ```
Автоматически будет выполнено:
- Миграции БД.
- Сидинг базовых категорий (`python manage.py seed_categories`).
- Запуск Daphne (порт 8000).
- Запуск Celery Worker & Beat.

### Локальный запуск (Разработка)

1. Установите зависимости: `pip install -r requirements.txt`.
2. Примените миграции: `python manage.py migrate`.
3. Подготовьте переводы (i18n):
   ```bash
   python manage.py compilemessages
   ```
4. Запустите сервер:
   ```bash
   daphne -b 0.0.0.0 -p 8000 core.asgi:application
   ```

---

## 🌍 Интернационализация (i18n)

Бэкенд поддерживает три языка: Русский, Узбекский и Английский.
- Для получения сообщений на нужном языке передавайте заголовок: `Accept-Language: uz`.
- Для перевода контента в БД (категории) используются соответствующие поля или файлы переводов.

---

## 📚 API Документация

- **Swagger**: [http://localhost:8000/api/schema/swagger-ui/](http://localhost:8000/api/schema/swagger-ui/)
- **ReDoc**: [http://localhost:8000/api/schema/redoc/](http://localhost:8000/api/schema/redoc/)

Все ошибки возвращаются в стандартизированном JSON-формате через `core/exceptions.py`.

---

## 🔔 Уведомления

- **SMS**: Интеграция с Eskiz.uz.
- **Push**: Поддержка FCM токенов (хранятся в профиле пользователя).
- **Celery Beat**: Автоматические напоминания о возврате вещей и истечении сроков.
ориями (Свадебный декор, платья и тд):
   ```bash
   python manage.py seed_categories
   ```
6. Запустите все сервисы:
   ```bash
   python manage.py runserver            # Основной API
   celery -A core worker -l info         # Worker для отправки SMS/Email
   celery -A core beat -l info           # Планировщик (напоминания о дедлайнах)
   ```

---

## 📚 Документация API (Swagger / ReDoc)

Все роуты API автоматически документируются с помощью `drf-spectacular`. После запуска проекта документация доступна по ссылкам:

- **Swagger UI**: [http://localhost:8000/api/schema/swagger-ui/](http://localhost:8000/api/schema/swagger-ui/)
- **ReDoc**: [http://localhost:8000/api/schema/redoc/](http://localhost:8000/api/schema/redoc/)

Там описаны все DTO (Serializers), параметры фильтрации объявлений и способы взаимодействия с Webhook-ами оплат.

---

## 🕒 Фоновые задачи (Celery)
В проекте реализованы следующие асинхронные задачи:
- `notify_owner_new_booking`: Отправка SMS-уведомления владельцу (через Eskiz.uz) о новом запросе на бронь.
- `notify_expiring_bookings`: Ежедневная задача (Beat), отправляющая напоминания тем арендаторам, чей срок аренды истекает на следующий день.
- `release_escrow`: Асинхронный триггер для освобождения залога и выплаты денег владельцу после перевода сделки в статус `COMPLETED`.
