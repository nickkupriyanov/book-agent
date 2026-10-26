# Book Agent

Book Agent — учебный, но доведённый до конца проект: личная библиотека книг с
AI-агентом. Пользователь пишет обычным текстом («найди Дюну и добавь в список на
чтение»), а модель не получает прямой доступ к базе данных. Она выбирает
доступные инструменты, а backend проверяет каждый вызов и выполняет его в
ограниченных рамках.

> **Статус:** законченная учебная реализация, не production-ready сервис.
> Четыре MVP-сценария работают через HTTP и React, покрыты детерминированными
> тестами и evals. Настоящей аутентификации, асинхронного выполнения и
> production-инфраструктуры пока нет.

## Что умеет

1. **Показать библиотеку**

   > Покажи книги, которые я сейчас читаю.

2. **Найти и добавить книгу**

   > Найди «Дюну» и добавь её в список «Хочу прочитать».

3. **Изменить статус чтения**

   > Я дочитал «1984». Отметь её как прочитанную.

4. **Подобрать следующие книги**

   > Посмотри, что я недавно прочитал, и предложи три похожие книги, которых ещё нет в моей библиотеке.

Критерий успеха — не красивый текст модели, а состояние системы: книга найдена,
запись изменена ровно один раз, дубликаты исключены, запрещённые действия не
выполнялись.

Дополнительно реализованы:

- human-in-the-loop подтверждение destructive-действий;
- личные заметки и preferences с retrieval по заметкам;
- внешний каталог Open Library с timeout, retry, кэшем и локальным fallback;
- PostgreSQL как альтернатива SQLite;
- безопасные трассы запусков без сообщений и содержимого заметок;
- evals с проверкой состояния БД, а не только финального ответа.

## Демо за 60 секунд

Demo не требует API-ключа, сети, `.env` или запущенного сервера. Оно поднимает
временную SQLite и fake-провайдер, выполняет чтение, поиск с добавлением книги и
удаление через approval, затем печатает компактный JSON:

```bash
cd backend
uv sync
uv run python -m app.demo
```

Ожидаемые ключи ответа: `read`, `multi_step_write`, `approval`, `safe_traces`.

## Быстрый старт

### Требования

- Python 3.12;
- [uv](https://docs.astral.sh/uv/);
- Node.js 22.x для frontend;
- Docker — только если нужен PostgreSQL.

### Backend

Команды выполняются из корня проекта:

```bash
cd backend
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
```

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`

Для реальных ответов модели добавьте в `backend/.env`:

```dotenv
DEEPSEEK_API_KEY=...
```

Без ключа продолжают работать тесты, evals и demo на fake-провайдере.

### PostgreSQL

По умолчанию используется SQLite. Чистый локальный PostgreSQL, миграции и seed
поднимаются одной командой из корня:

```bash
./scripts/bootstrap-postgres.sh
```

Если порт `5432` занят:

```bash
POSTGRES_PORT=55432 docker compose up -d --wait postgres
```

и используйте тот же порт в `DATABASE_URL` и `TEST_POSTGRES_ADMIN_URL`.

Чтобы постоянно работать с PostgreSQL, замените `DATABASE_URL` в
`backend/.env` — это единственная настройка, которая выбирает СУБД:

```dotenv
DATABASE_URL=postgresql+psycopg://book_agent:book_agent@localhost:5432/book_agent
```

Затем повторите миграции и seed. Остановка без удаления данных:

```bash
docker compose down
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

UI: `http://localhost:5173`. Vite проксирует `/api` на `http://127.0.0.1:8000`.

> Для тестов нужен Node.js 22. На Node 26.11 jsdom-тесты падают с ошибкой
> `localStorage is not available for opaque origins`; `build` и `lint` при этом
> проходят. Исправление зафиксировано в [ROADMAP.md](./ROADMAP.md).

## Конфигурация

Переменные читаются из `backend/.env`; значения по умолчанию — в
`backend/app/config.py`.

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./book_agent.db` | SQLite или PostgreSQL |
| `DEMO_USER_ID` | `00000000-...-0001` | Учебная подмена аутентификации |
| `DEEPSEEK_API_KEY` | пусто | Ключ реального провайдера |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | Base URL провайдера |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | Модель |
| `DEEPSEEK_TIMEOUT_SECONDS` | `30` | Таймаут запроса к модели |
| `AGENT_MAX_STEPS` | `5` | Максимум обращений к модели на запуск |
| `AGENT_HISTORY_MAX_TOOL_ROUNDS` | `3` | Сколько tool-раундов истории видит модель |
| `PENDING_ACTION_TTL_SECONDS` | `900` | Срок жизни запроса подтверждения |
| `CATALOG_PROVIDER` | `local` | `local` или `open_library` |
| `OPEN_LIBRARY_BASE_URL` | `https://openlibrary.org` | Внешний каталог |
| `OPEN_LIBRARY_TIMEOUT_SECONDS` | `3` | Таймаут внешнего каталога |
| `OPEN_LIBRARY_MAX_RETRIES` | `1` | Повторы при временной ошибке |
| `CATALOG_CACHE_TTL_SECONDS` | `300` | TTL in-memory кэша |
| `CATALOG_CACHE_MAX_ENTRIES` | `128` | Размер кэша |

## API

Все запросы работают от одного `DEMO_USER_ID`. Полная схема — в Swagger.

| Метод | Путь | Назначение |
| --- | --- | --- |
| `POST` | `/api/agent/runs` | Синхронно выполнить запрос агента |
| `GET` | `/api/agent/runs/{run_id}` | Получить запуск и его шаги |
| `GET` | `/api/agent/runs/{run_id}/trace` | Безопасная диагностическая трасса |
| `POST` | `/api/agent/runs/{run_id}/actions/{action_id}/approve` | Подтвердить действие |
| `POST` | `/api/agent/runs/{run_id}/actions/{action_id}/reject` | Отклонить действие |
| `GET` | `/api/books/search?q=...` | Поиск книги в каталоге |
| `GET` | `/api/books/{book_id}` | Книга по ID |
| `GET` | `/api/library?status=...` | Библиотека с фильтром |
| `POST` | `/api/library` | Добавить книгу |
| `PATCH` | `/api/library/{book_id}/status` | Изменить статус |
| `POST` | `/api/notes` | Создать заметку |
| `GET` | `/api/notes` | Список заметок |
| `GET` | `/api/notes/{note_id}` | Заметка по ID |
| `PUT` | `/api/notes/{note_id}` | Обновить заметку |
| `DELETE` | `/api/notes/{note_id}` | Удалить заметку |
| `GET` | `/api/preferences` | Preferences пользователя |
| `PUT` | `/api/preferences/{key}` | Сохранить preference |

Пример запуска агента:

```bash
curl -X POST http://localhost:8000/api/agent/runs \
  -H 'Content-Type: application/json' \
  -d '{"message":"Найди Дюну и добавь в список на чтение"}'
```

Если модель предлагает destructive-действие, ответ приходит со статусом
`waiting_for_approval` и `pending_action`. Подтверждение не принимает новых
аргументов — только пустой объект:

```bash
curl -X POST \
  http://localhost:8000/api/agent/runs/RUN_ID/actions/ACTION_ID/approve \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Первый approve атомарно фиксирует эффект и сохраняет результат. Повторная
доставка возвращает сохранённый результат и не выполняет действие второй раз.
Reject не вызывает destructive handler, сохраняет `user_rejected` и продолжает
тот же запуск, если остался бюджет шагов. После `expires_at` действие получает
статус `expired`, а запуск завершается с `approval_expired`.

## Как работает агент

Обычный LLM-чат получает текст и возвращает текст. Здесь модель включена в
управляемый цикл:

1. пользователь формулирует цель;
2. модель решает, нужен ли инструмент;
3. backend проверяет имя инструмента и аргументы по строгой схеме;
4. зарегистрированный handler выполняет ограниченное действие;
5. результат возвращается модели;
6. модель выбирает следующий шаг или формирует ответ;
7. backend останавливает цикл по результату, ошибке, ожиданию подтверждения или
   лимиту шагов.

Модель предлагает действия, но не исполняет их. Контроль, доступ к данным,
правила безопасности и критерии остановки принадлежат приложению.

Состояния запуска: `running`, `waiting_for_approval`, `completed`, `failed`,
`step_limit_exceeded`.

## Архитектура

```mermaid
flowchart LR
    U["Пользователь"] --> UI["React + TypeScript"]
    UI --> API["FastAPI"]
    API --> LOOP["Agent loop"]
    LOOP --> LLM["LLMProvider"]
    LLM --> LOOP
    LOOP --> REG["Tool registry"]
    REG --> SVC["Book service"]
    REG --> MEMORY["User notes retrieval"]
    SVC --> REPO["Repositories"]
    MEMORY --> REPO
    REPO --> DB[("SQLite / PostgreSQL")]
    REG --> CATALOG["Open Library + local fallback"]
    LOOP --> TRACE["Runs and traces"]
```

Ключевые границы:

- React общается только с HTTP API;
- agent loop зависит от контракта `LLMProvider`, а не от SDK конкретного
  провайдера;
- модель видит только опубликованные определения инструментов;
- tools вызывают доменные сервисы, но не содержат произвольный SQL;
- доменная логика книг работает и без LLM;
- `user_id` берётся на сервере и не передаётся моделью;
- destructive-действие сначала создаёт `PendingAction`, а меняет БД только после
  отдельного approval.

Подробная карта зависимостей, write flow и границы доверия —
в [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

### Инструменты

| Инструмент | Назначение | Тип |
| --- | --- | --- |
| `search_books` | Найти книгу в каталоге | read |
| `find_similar_books` | Найти похожие книги без книг из библиотеки | read |
| `get_user_library` | Получить библиотеку с фильтром по статусу | read |
| `add_book` | Добавить книгу в библиотеку | write |
| `update_book_status` | Изменить статус чтения | write |
| `remove_book` | Удалить книгу после approval | destructive |
| `search_user_notes` | Найти фрагменты личных заметок | read |

### Память и RAG

Память разделена по назначению:

- история текущего запуска ограничена последними полными tool-раундами;
- структурированные preferences хранятся отдельно по ключам;
- заметки индексируются фрагментами и извлекаются только явным tool.

Retrieval детерминированный, Unicode-aware и лексический: он не требует
embedding API и оставляет границу для будущей замены алгоритма. Каждый результат
содержит `chunk_id`, `note_id`, необязательный `book_id` и исходный fragment.
Содержимое заметок считается недоверенным данным и не может менять policy.

## Evals и observability

Обязательный набор запускается без API-ключа и сети:

```bash
cd backend
uv run python -m app.evals.cli
```

Сохранить отчёт:

```bash
uv run python -m app.evals.cli --output ../evals/report.json
```

Сравнить два отчёта на одной версии dataset:

```bash
uv run python -m app.evals.cli --output /tmp/baseline-report.json
uv run python -m app.evals.cli --provider deepseek --output /tmp/candidate-report.json
uv run python -m app.evals.compare /tmp/baseline-report.json /tmp/candidate-report.json
```

Проверить зафиксированный deterministic baseline:

```bash
uv run python -m app.evals.baseline
```

Live-запуск всегда явный и требует `DEEPSEEK_API_KEY`:

```bash
uv run python -m app.evals.cli --provider deepseek
```

Текущий dataset: 21 сценарий, baseline — 21/21, tool precision и recall 1.0,
0 forbidden и 0 invalid calls. Отчёт содержит task success, tool
precision/recall, число шагов, latency и token usage. Критерии проверяют
состояние БД, поэтому уверенный текст без фактического изменения считается
провалом.

Safe trace содержит `run_id`, provider/model/prompt version, шаги и redacted tool
data, но не историю сообщений и не содержимое заметок.

## Тесты

```bash
cd backend
uv run pytest
```

- 267 passed, 3 skipped;
- тесты не используют LLM и внешнюю сеть;
- PostgreSQL-тесты опциональны:

```bash
cd backend
TEST_POSTGRES_ADMIN_URL=postgresql+psycopg://book_agent:book_agent@localhost:5432/postgres \
  uv run pytest
```

Frontend (Node 22):

```bash
cd frontend
npm test
npm run build
npm run lint
```

- 39 frontend-тестов;
- `build` и `lint` проходят и на Node 26, тесты — только на Node 22.

Реальный Open Library не входит в основной suite:

```bash
cd backend
OPEN_LIBRARY_TIMEOUT_SECONDS=15 RUN_OPEN_LIBRARY_SMOKE=1 \
  uv run pytest -m network
```

## Ограничения

Главное ограничение — `DEMO_USER_ID` вместо аутентификации. Сервис нельзя
публиковать для нескольких пользователей без identity, авторизации и tenant
isolation. Также:

- agent loop синхронный: нет очереди, streaming, отмены и фонового worker'а;
- retrieval лексический, без embeddings;
- external catalog fallback и кэш рассчитаны на один процесс;
- raw `AgentRun` хранит полную рабочую историю, а safe trace — нет;
- fake evals проверяют код и известные сценарии, но не доказывают качество
  реальной модели;
- нет деплоя, TLS, secret manager, мониторинга, бэкапов и нагрузочных тестов.

Полный список угроз, controls и остаточных рисков —
в [docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md). План развития —
в [ROADMAP.md](./ROADMAP.md).

Сознательно не используются: LangChain/LangGraph/CrewAI, multi-agent, MCP,
browser automation, автономные фоновые задачи, сложный planner и векторная база
«для всей памяти». Причины и измеримые триггеры пересмотра —
в [ADR-001](./docs/adr/001-agent-orchestration.md).

## Структура проекта

```text
book-agent/
├── backend/
│   ├── app/
│   │   ├── agent/           # loop, state, persistence, approvals
│   │   ├── catalog/         # local/Open Library adapters и fallback
│   │   ├── evals/           # runner, evaluator, baseline и comparison
│   │   ├── llm/             # provider contract, fake и DeepSeek adapter
│   │   ├── memory/          # notes, preferences, chunks и retrieval
│   │   ├── tools/           # schemas, registry, handlers и policy
│   │   ├── api.py           # HTTP endpoints
│   │   ├── dependencies.py  # composition root
│   │   ├── demo.py          # автономный HTTP demo
│   │   └── observability.py # безопасная trace
│   ├── migrations/
│   └── tests/
├── frontend/
│   └── src/                 # React UI, API client и strict decoder
├── evals/
│   ├── datasets/            # versioned scenario inputs
│   └── baselines/           # stable expected metrics
├── docs/
│   ├── ARCHITECTURE.md
│   ├── THREAT_MODEL.md
│   └── adr/
├── scripts/
├── README.md
└── ROADMAP.md
```

## Документация

- [ROADMAP.md](./ROADMAP.md) — приоритеты и план будущих доработок;
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) — слои, зависимости и потоки;
- [docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md) — угрозы, controls, остаточные
  риски;
- [docs/adr/001-agent-orchestration.md](./docs/adr/001-agent-orchestration.md) —
  почему оставлен собственный agent loop;
- [frontend/README.md](./frontend/README.md) — запуск интерфейса.

История разработки и учебные материалы ранних версий сохранены в git-теге
`archive/learning-docs-2026-09`.

## Принцип

Качество агента определяется не только моделью. Надёжность создают строгие
инструменты, ограниченный цикл, проверяемое состояние, approvals,
идемпотентность, тесты и наблюдаемость.
