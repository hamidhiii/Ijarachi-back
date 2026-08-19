# Rentoo - P2P Rental Platform (Backend)

Backend часть для платформы шеринга (P2P аренды вещей), сфокусированной на стартовом MVP для категории "Той и праздники" (свадебный декор, платья, посуда, и т.д). Платформа позволяет арендовать вещи у других людей в Узбекистане с безопасной оплатой через Эскроу.

## 🚀 Технологический стек

- **Язык**: Python 3.11+
- **Фреймворк**: Django 4.2+, Django REST Framework (DRF)
- **База Данных**: PostgreSQL
- **Брокер/Кэш/WebSocket layer**: Redis
- **Фоновые задачи**: Celery + Celery Beat
- **Авторизация**: JWT (SimpleJWT)
- **Контейнеризация**: Docker & Docker Compose
- **Провайдеры SMS/оплат**: Eskiz.uz, Payme, Click
- **KYC**: собственный пайплайн (OCR паспорта/ID-карты + сверка лица с liveness), без сторонних сервисов

---

## 🏗 Архитектура модулей (Apps)

1. **`users`** — Пользователи, авторизация по телефону (OTP), профиль, собственный KYC (паспорт/ID + сверка лица), смена телефона через SMS.
2. **`catalog`** — Категории и объявления (`/listings`) с модерацией, фото, геолокацией, поиском и статистикой владельца.
3. **`bookings`** — Сделки (`/deals`) со статусной машиной draft -> pending_payment -> paid -> in_progress -> returned -> completed/cancelled/disputed и защитой от двойного бронирования.
4. **`payments`** — Интеграция с Payme (JSON-RPC) и Click (SHOP API). Логика временного удержания денег на счету компании до момента завершения сделки и возвращения залога (Escrow).
5. **`chat`** — Conversation/Message, история через REST и realtime WebSocket.
6. **`notifications`** — In-app уведомления, шаблоны и audit log.

---

## 🛠 Установка и Запуск

### Запуск через Docker (Рекомендуемый)
Для быстрого запуска вам достаточно установленного `docker-compose`.

1. Склонируйте репозиторий:
   ```bash
   git clone https://github.com/hamidhiii/Ijarachi-back.git
   cd Ijarachi-back
   ```
2. Подготовьте `.env` файл на основе примера:
   ```bash
   cp .env.example .env
   ```
   *(При необходимости пропишите ключи доступа для Click, Payme и Eskiz)*
3. Соберите и запустите контейнеры:
   ```bash
   docker compose up -d --build
   ```

Первичный запуск автоматически:
- Накатит все миграции на PostgreSQL.
- Засеет базу данных категориями для "Той и праздники".
- Поднимет веб-модуль Django (порт 8000), Celery Worker и Celery Beat.

Docker Compose сам подставляет контейнерам `DB_HOST=db`, `DB_PORT=5432` и `REDIS_URL=redis://redis:6379/0`.
В `.env` можно оставить `DB_HOST=localhost` для запуска Django напрямую на хосте.
PostgreSQL и Redis в compose привязаны к `127.0.0.1`, чтобы не открывать их наружу на VPS.

Если в логах PostgreSQL есть попытки `COPY ... TO PROGRAM`, создание неизвестных users/roles или скачивание файлов в `/tmp`, считайте текущий database volume скомпрометированным:

```bash
docker compose down
docker volume rm ijarachi-back_postgres_data
# затем задайте новый DB_PASSWORD в .env
docker compose up -d --build
```

На продакшене дополнительно закройте порты `5432/5433` и `6379/6380` firewall-ом для внешнего доступа.

---

### Запуск локально (Без Docker)
Если вы хотите запустить проект локально для разработки:

1. Создайте виртуальное окружение:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Для Windows: .\venv\Scripts\activate
   ```
2. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
3. Поднимите локально PostgreSQL и Redis, передайте их данные в `.env`.
   Для запуска без Docker используйте `DB_HOST=localhost` или `DB_HOST=127.0.0.1`.
   Значение `DB_HOST=db` работает только внутри сети Docker Compose.
4. Выполните миграции:
   ```bash
   python manage.py migrate
   ```
5. Засейте базу стартовыми категориями (Свадебный декор, платья и тд):
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

- **Swagger UI**: [http://localhost:8000/api/docs/](http://localhost:8000/api/docs/)
- **ReDoc**: [http://localhost:8000/api/schema/redoc/](http://localhost:8000/api/schema/redoc/)

Там описаны все DTO (Serializers), параметры фильтрации объявлений и способы взаимодействия с Webhook-ами оплат.

---

## 🕒 Фоновые задачи (Celery)
В проекте реализованы следующие асинхронные задачи:
- `notify_owner_new_booking`: Отправка SMS-уведомления владельцу (через Eskiz.uz) о новом запросе на сделку.
- `notify_expiring_bookings`: Ежедневная задача (Beat), отправляющая напоминания тем арендаторам, чей срок аренды истекает на следующий день.
- `release_escrow`: Асинхронный триггер для освобождения залога и выплаты денег владельцу после перевода сделки в статус `COMPLETED`.
