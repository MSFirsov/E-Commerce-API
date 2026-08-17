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

PostgreSQL и Redis подняты в compose, но приложение к ним пока не обращается —
подключение и миграции на следующем этапе.

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
make lint        # ruff check + ruff format --check
make typecheck   # mypy
make test        # pytest
make check       # всё сразу — то же, что гоняет CI
make logs        # логи приложения
```

## Структура

```
src/app/
  main.py            create_app() и lifespan
  core/
    config.py        настройки приложения
  modules/           вертикальные срезы по доменам
    health/
      router.py
tests/
```

Приложение построено как модульный монолит: каждый домен (каталог, корзина, заказы,
платежи) — отдельный пакет в `modules/` со своими роутером, схемами и сервисом.
Слоя репозиториев нет: `AsyncSession` в SQLAlchemy 2.0 уже реализует Unit of Work,
и дублировать его обёрткой значило бы добавить код без новых возможностей.
