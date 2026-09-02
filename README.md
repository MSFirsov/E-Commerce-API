# E-Commerce-API

REST API интернет-магазина на FastAPI — каталог, корзина,
оформление заказа и онлайн-оплата.
Проект в разработке.

## Стек

Python 3.13 · FastAPI · Pydantic v2 · uv · Docker Compose · PostgreSQL 17 · Redis 7 ·
Ruff · mypy (strict) · pytest · GitHub Actions

## Что уже работает

- Приложение на FastAPI с фабрикой `create_app()` и эндпоинтом `GET /health`
- Конфигурация через pydantic-settings: обязательные поля без значений по умолчанию,
  приложение не стартует при неполном окружении
- Docker-образ: multi-stage, запуск от непривилегированного пользователя, 257 МБ
- `docker compose`: приложение, PostgreSQL 17 и Redis 7 с healthcheck'ами
- Проверки: Ruff, mypy в строгом режиме, pytest, pre-commit (включая поиск секретов)
- CI на GitHub Actions: три параллельные джобы — линтер, типы, тесты
- Асинхронный SQLAlchemy 2.0 + asyncpg, пул соединений с `pool_pre_ping`
- Alembic-миграции (async), первая — таблица `users`
- `GET /health/db` проверяет доступность базы, `GET /health` — только что процесс жив
- Единый формат ошибок RFC 9457 (Problem Details) и заголовок `X-Request-ID` на любом ответе
- Тесты гоняются на реальном PostgreSQL, изоляция — транзакция с SAVEPOINT на каждый тест
- Регистрация и вход: `POST /auth/register`, `POST /auth/login`, `GET /users/me`
- Пароли — argon2id (`pwdlib`), хэширование вынесено в отдельный поток, не блокирует event loop
- Access-токен — JWT (PyJWT, HS256), 15 минут жизни; в `/docs` есть кнопка Authorize

Redis поднят в compose, но приложение к нему пока не обращается — кэш и очереди на
следующих этапах.

## Запуск

Нужны Docker и [uv](https://docs.astral.sh/uv/).

```bash
git clone git@github.com:MSFirsov/E-Commerce-API.git
cd E-Commerce-API
cp .env.example .env          # при желании поправить значения
make up                       # docker compose up -d --build
curl localhost:8000/health    # {"status":"ok"}
```

Документация API — http://localhost:8000/docs

Остановить: `make down`

### Локально, без контейнера приложения

База и Redis всё равно нужны, поэтому поднимаем их через compose, а приложение
запускаем на хосте:

```bash
uv sync
docker compose up -d postgres redis
uv run uvicorn app.main:create_app --factory --reload
```

В `.env` хосты указаны как `localhost` — это значения для запуска с хост-машины.
Внутри compose сервис `api` получает `POSTGRES_HOST=postgres` через `environment`.

### Команды

```bash
make lint                       # ruff check + ruff format --check
make typecheck                  # mypy
make test                       # pytest
make check                      # всё сразу — то же, что гоняет CI
make logs                       # логи приложения
make migrate                    # alembic upgrade head
make revision m="add orders"    # alembic revision --autogenerate
make downgrade                  # alembic downgrade -1
make db-shell                   # psql внутри контейнера postgres
```

## Структура

```
src/app/
  main.py            create_app() и lifespan
  core/
    config.py        настройки приложения
    db.py            async engine, session_factory, get_session
    deps.py          общие Depends (DbSession, CurrentUser)
    errors.py        AppError и RFC 9457 Problem Details
    request_id.py    middleware + ContextVar для X-Request-ID
    security.py      хэш паролей (argon2id) и JWT (PyJWT)
  models/            все SQLAlchemy-модели одним пакетом
  modules/           вертикальные срезы по доменам
    health/
      router.py
    auth/            регистрация, логин, выпуск JWT
      router.py
      schemas.py
      service.py
    users/           GET /me
      router.py
      schemas.py
migrations/          Alembic (async), env.py, versions/
tests/
  conftest.py        тестовая БД, изоляция транзакцией с SAVEPOINT
```

Приложение построено как модульный монолит: каждый домен (каталог, корзина, заказы,
платежи) — отдельный пакет в `modules/` со своими роутером, схемами и сервисом.
Слоя репозиториев нет: `AsyncSession` в SQLAlchemy 2.0 уже реализует Unit of Work,
и дублировать его обёрткой значило бы добавить код без новых возможностей.

## База данных

Таблица `users`: `id` (UUID), `email` (уникальный), `password_hash`, `full_name`,
`role`, `is_active`, `email_verified_at`, `created_at`/`updated_at`. `role` — это
`VARCHAR(32)` с `CHECK`, а не нативный PostgreSQL ENUM: добавить новое значение
в ENUM — это блокирующая миграция таблицы, а `CHECK` меняется без блокировки и
значения видны прямо в `\d users`, без похода в `pg_enum`.

Первичный ключ — UUID (`gen_random_uuid()`), а не автоинкремент: id не выдаёт
количество заказов и пользователей конкурентам и не даёт перебирать чужие записи
по номеру. Плата за это честная — случайный UUID фрагментирует B-tree индекс
первичного ключа сильнее, чем последовательный `bigint`; на больших таблицах это
решается UUIDv7 (первые биты — таймстемп, вставки снова монотонны), но это уже
отдельная оптимизация, не обязательная на старте.

Пул соединений: `pool_size=5, max_overflow=10` на процесс — до 15 соединений
с базой от одного воркера uvicorn. Реальный лимит считается как
`(pool_size + max_overflow) × число процессов` и должен помещаться в
`max_connections` PostgreSQL с запасом на служебные подключения (миграции,
админ-доступ).

Тесты не используют `Base.metadata.create_all` — схема накатывается теми же
Alembic-миграциями, что и в проде, иначе тесты проверяли бы не то, что реально
задеплоится. Изоляция — одна внешняя транзакция на тест с `SAVEPOINT`
(`join_transaction_mode="create_savepoint"`): что бы тест ни закоммитил внутри,
после него всё откатывается, и тесты не зависят от порядка запуска.

## Аутентификация

Пароли хранятся как argon2id-хэш (`pwdlib`), а не bcrypt: у bcrypt пароль молча
обрезается до 72 байт, а argon2id — memory-hard функция, победитель Password
Hashing Competition, рекомендован OWASP. Хэширование стоит десятки миллисекунд
и намеренно тяжёлое — если считать его прямо в `async def`, это на всё это время
блокирует event loop и, как следствие, все остальные запросы приложения, поэтому
вызов вынесен в отдельный поток через `anyio.to_thread`.

Access-токен — JWT (PyJWT, алгоритм HS256), живёт 15 минут. В claims — стандартные
`sub`/`iat`/`exp`/`iss`/`aud`/`jti` (RFC 7519) и свои `typ`/`role`. `iss`/`aud`
проверяются при декодировании, чтобы токен, выпущенный тем же секретом для другой
цели, не прошёл; список разрешённых алгоритмов передаётся явно, а не берётся из
заголовка токена — иначе токен с `alg: none` прошёл бы проверку сам себя.
Честная оговорка: пока это единственный вид токена, без ротации и отзыва — refresh
и логаут на следующем этапе.

Ответ `/auth/login` на неверный пароль и на несуществующий email — один и тот же
код и тело. Без этого по разнице ответов (или по времени, если для несуществующего
email проверку пароля вообще пропустить) можно было бы перебором узнать, какие
email вообще зарегистрированы в системе, не имея ни одного пароля.
