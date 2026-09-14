# Book Agent

Учебный проект для последовательного изучения AI-агентов на примере личной библиотеки книг.

Пользователь сможет попросить агента найти книгу, посмотреть библиотеку, изменить статус чтения или подобрать следующую книгу. Модель при этом не получает прямой доступ к базе данных: она выбирает доступные инструменты, а backend валидирует и безопасно выполняет каждый вызов.

> **Статус:** все 11 этапов завершены. Проект имеет архитектурные и security
> contracts, воспроизводимый HTTP demo, frozen eval baseline, threat model и
> ADR о выборе agent orchestration. Это законченный учебный проект, а не
> production-ready сервис.

## Зачем нужен этот проект

Цель проекта — не собрать максимально сложного или автономного агента, а самостоятельно пройти весь путь от обычного backend-приложения до контролируемой агентной системы.

В ходе работы будут последовательно реализованы:

- agent loop;
- function/tool calling;
- строгие схемы входов и результатов;
- многошаговое выполнение задач;
- состояние запусков и защита от циклов;
- human-in-the-loop для подтверждения действий;
- память и RAG по пользовательским заметкам;
- evals;
- логи и трассировка запусков.

Подробная учебная программа находится в [ROADMAP.md](./ROADMAP.md), фактические
зависимости — в [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md), а остаточные
риски — в [docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md).

## MVP-сценарии

Backend MVP поддерживает четыре сценария:

1. **Посмотреть текущие книги**

   > Покажи книги, которые я сейчас читаю.

2. **Найти и добавить книгу**

   > Найди «Дюну» и добавь её в список «Хочу прочитать».

3. **Изменить статус чтения**

   > Я дочитал «1984». Отметь её как прочитанную.

4. **Выполнить многошаговую рекомендацию**

   > Посмотри, что я недавно прочитал, и предложи три похожие книги, которых ещё нет в моей библиотеке.

Успех определяется не красотой ответа модели, а итоговым состоянием системы: нужная книга найдена, запись изменена ровно один раз, дубликаты исключены, запрещённые действия не выполнялись.

## Что делает систему агентом

Обычный LLM-чат получает текст и возвращает текст. В этом проекте модель включена в управляемый цикл:

1. пользователь формулирует цель;
2. модель решает, нужен ли инструмент;
3. backend проверяет имя инструмента и его аргументы;
4. инструмент выполняет ограниченное действие;
5. результат возвращается модели;
6. модель выбирает следующий шаг или формирует финальный ответ;
7. backend останавливает цикл по результату, ошибке, ожиданию подтверждения или лимиту шагов.

Модель предлагает действия, но не исполняет их самостоятельно. Контроль, доступ к данным, правила безопасности и критерии остановки принадлежат приложению.

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

Основные границы системы:

- React общается только с HTTP API;
- agent loop зависит от контракта `LLMProvider`, а не от SDK конкретного провайдера;
- модель видит только опубликованные определения инструментов;
- инструменты вызывают доменные сервисы, но не содержат произвольный SQL;
- доменная логика книг работает и без LLM;
- трейс запуска хранится отдельно от пользовательского ответа.

## Основные контракты

Это упрощённое представление текущих интерфейсов без деталей валидации.

```python
class LLMProvider(Protocol):
    def generate(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> ModelResponse: ...
```

`LLMProvider` описывает только возможности, которые действительно нужны agent loop. Параметры конкретного API — идентификатор предыдущего ответа, reasoning-настройки, usage и сырые события — преобразуются внутри адаптера и не протекают в доменный слой.

```python
@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    access: ToolAccess
    arguments_model: type[BaseModel]
    result_model: type[BaseModel]

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, object]

class ToolResult(BaseModel):
    tool_call_id: str
    tool_name: str
    output: dict[str, object] | None = None
    error: ToolError | None = None
```

Реализованные инструменты backend MVP:

| Инструмент | Назначение | Тип |
| --- | --- | --- |
| `search_books` | Найти книги в каталоге | read |
| `find_similar_books` | Найти похожие книги и исключить текущую библиотеку | read |
| `get_user_library` | Получить библиотеку с фильтром по статусу | read |
| `add_book` | Добавить книгу в библиотеку | write |
| `update_book_status` | Изменить статус существующей книги | write |
| `remove_book` | Удалить книгу после отдельного строгого approval | destructive |
| `search_user_notes` | Найти подтверждающие фрагменты в личных заметках | read |

Память разделена по назначению:

- история текущего agent run ограничена последними полными tool-раундами;
- структурированные preferences хранятся отдельно по ключам;
- свободные заметки индексируются фрагментами и извлекаются только явным tool.

Локальный retrieval использует детерминированное Unicode-aware лексическое
ранжирование. Оно не требует внешнего embedding API и сохраняет архитектурную
границу для будущей замены поискового алгоритма. Каждый результат содержит
`chunk_id`, `note_id`, необязательный `book_id` и исходный fragment.

## Evals и observability

Обязательный eval-набор запускается из `backend/` без API key и сети:

```bash
uv run python -m app.evals.cli
```

Чтобы сохранить отчёт:

```bash
uv run python -m app.evals.cli --output ../evals/report.json
```

Два полных отчёта на одной версии dataset сравниваются командой:

```bash
uv run python -m app.evals.cli --output /tmp/baseline-report.json
uv run python -m app.evals.cli --provider deepseek --output /tmp/candidate-report.json
uv run python -m app.evals.compare /tmp/baseline-report.json /tmp/candidate-report.json
```

Зафиксированный deterministic baseline проверяется отдельно. Он намеренно не
содержит случайные run IDs, timestamp и latency:

```bash
uv run python -m app.evals.baseline
```

Запуск реальной модели всегда явный и требует `DEEPSEEK_API_KEY`:

```bash
uv run python -m app.evals.cli --provider deepseek
```

Отчёт содержит task success, tool precision/recall, forbidden и invalid calls,
число шагов, latency и token usage при наличии. Критерии проверяют состояние БД,
поэтому уверенный финальный текст без фактического изменения считается
провалом. Safe trace содержит `run_id`, provider/model/prompt version, шаги и
redacted tool data, но не историю сообщений или содержимое заметок.

Реализованные состояния `AgentRun`:

- `running`;
- `waiting_for_approval`;
- `completed`;
- `failed`;
- `step_limit_exceeded`.

В `waiting_for_approval` запуск уже содержит проверенное ожидающее действие, но
destructive handler ещё не вызван. Approve или reject сохраняет решение и
возобновляет тот же запуск; повторная доставка не применяет действие второй раз.

Каждый `AgentStep` соответствует одному обращению к модели и хранит номер шага, снимок истории сообщений, нормализованный ответ, результаты tools, ошибку и длительность.

## Стек

### Backend

- Python;
- FastAPI;
- Pydantic;
- SQLAlchemy;
- Alembic;
- SQLite на первых этапах;
- PostgreSQL после стабилизации доменных контрактов;
- pytest.

### Frontend

- React;
- TypeScript;
- Vite;
- Vitest.

### Интеграции

- локальный детерминированный каталог книг на старте;
- внешний каталог, например Open Library, на отдельном этапе;
- провайдер-независимый `LLMProvider`;
- DeepSeek Chat Completions как первая реальная реализация адаптера;
- fake-провайдер для unit-тестов.

## Фактическая структура проекта

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
├── README.md
└── ROADMAP.md
```

## Как работать с роадмапом

1. Проходить этапы по порядку, не привязываясь к календарю.
2. Перед реализацией прочитать блок «Что понять» и своими словами сформулировать поток данных.
3. Реализовать только перечисленный вертикальный сценарий.
4. Добавить позитивные тесты и минимум один негативный тест.
5. Проверить критерии готовности и ответить на вопросы для самопроверки.
6. Записать выводы прямо в `ROADMAP.md` или в сообщение отдельного commit.
7. Сделать небольшой commit, который относится только к завершённому этапу.

Не переходите дальше, если сценарий работает только при ручном разговоре с моделью, но не имеет автоматической проверки результата.

### Обязательный учебный отчёт

После каждого этапа или микроэтапа недостаточно сообщить список файлов и
результат тестов. Итоговый отчёт должен быть понятен человеку, который учится
на изменениях, и обязательно содержать:

1. **Что сделали:** фактические изменения и новый поток данных от входа до
   наблюдаемого результата.
2. **Зачем:** какую проблему, риск или неопределённость устраняет каждый
   существенный элемент решения.
3. **На что обратить внимание:** инварианты, границы доверия, компромиссы и
   типичные ошибочные реализации.
4. **Как проверили:** конкретные тестовые сценарии, команды и фактический
   результат, включая негативные проверки.
5. **Что мы выучили:** переносимые инженерные принципы, а не пересказ списка
   изменённых файлов.
6. **Советы на будущее:** что учитывать в следующих шагах и что пока не следует
   преждевременно усложнять.
7. **Вопросы для самоконтроля с ответами:** несколько содержательных вопросов,
   которые проверяют понимание причин и границ решения. Вопросы вида «какой
   метод добавили?» не подходят; хороший вопрос требует объяснить угрозу,
   выбрать между альтернативами или предсказать поведение системы при ошибке.

Этот отчёт даётся в сообщении после завершения работы. Ключевые решения и
ответы, которые понадобятся в следующих сессиях, также сохраняются в документе
соответствующего этапа.

## Запуск

Для backend нужны Python 3.12 и [uv](https://docs.astral.sh/uv/). Команды выполняются из корня проекта.

### Backend

```bash
cd backend
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
```

API будет доступен на `http://localhost:8000`, интерактивная схема — на `http://localhost:8000/docs`.

Самодостаточный demo использует временную SQLite и fake LLM, поэтому ему не
нужны `.env`, API key, сервер или сеть:

```bash
cd backend
uv run python -m app.demo
```

По умолчанию backend использует SQLite. Чистый локальный PostgreSQL, миграции и
seed поднимаются из корня проекта одной командой:

```bash
./scripts/bootstrap-postgres.sh
```

Если локальный порт `5432` уже занят, задайте другой, например
`POSTGRES_PORT=55432 docker compose up -d --wait postgres`, и используйте тот же
порт в `DATABASE_URL` и `TEST_POSTGRES_ADMIN_URL`.

Чтобы постоянно запускать backend на PostgreSQL, замените `DATABASE_URL` в
`backend/.env`. Это единственная настройка, которая выбирает СУБД:

```dotenv
DATABASE_URL=postgresql+psycopg://book_agent:book_agent@localhost:5432/book_agent
```

```bash
cd backend
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
```

PostgreSQL создаётся с нуля; перенос данных из существующего SQLite-файла в
этот этап не входит. Остановить контейнер без удаления данных можно командой
`docker compose down` из корня проекта.

При `CATALOG_PROVIDER=open_library` поиск сначала обращается к Open Library.
Успешные результаты кэшируются в памяти и сохраняются в БД. После исчерпания
временной сетевой ошибки backend возвращает локальный fallback с
`degraded=true`; React показывает, что такой результат может быть неполным.

Синхронный запуск агента:

```bash
curl -X POST http://localhost:8000/api/agent/runs \
  -H 'Content-Type: application/json' \
  -d '{"message":"Найди Дюну и добавь в список на чтение"}'
```

Endpoint возвращает финальное состояние `AgentRun` и упорядоченный трейс шагов. Максимальное число обращений к модели задаётся через `AGENT_MAX_STEPS` и по умолчанию равно `5`.

Безопасная диагностическая trace без сообщений и содержимого заметок доступна
по `GET /api/agent/runs/{run_id}/trace`.

Для destructive-сценария первый запрос возвращает
`waiting_for_approval` и `pending_action`. Подтверждение не принимает новых
arguments — только пустой объект по сохранённым ID:

```bash
curl -X POST \
  http://localhost:8000/api/agent/runs/RUN_ID/actions/ACTION_ID/approve \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Первый approve атомарно фиксирует эффект и result, затем продолжает agent loop.
Повторная доставка возвращает сохранённый результат без повторного handler.

Отклонение использует тот же строгий пустой запрос:

```bash
curl -X POST \
  http://localhost:8000/api/agent/runs/RUN_ID/actions/ACTION_ID/reject \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Reject не вызывает destructive handler, сохраняет `user_rejected` как связанный
tool result и продолжает тот же run, если остался бюджет шагов.

Если два запроса подтверждения приходят одновременно, база данных выдаёт право
на исполнение только одному из них. Второй запрос получает уже сохранённый
результат и не удаляет книгу повторно. После `expires_at` действие переводится в
`expired`, а запуск завершается с причиной `approval_expired`. Отсутствующее и
чужое действие одинаково возвращают `404`, поэтому API не раскрывает наличие
чужих запросов подтверждения.

Ручной smoke рекомендации через реальный настроенный provider выполняется после
того, как в библиотеке есть хотя бы одна книга со статусом `finished`:

```bash
curl -X POST http://localhost:8000/api/agent/runs \
  -H 'Content-Type: application/json' \
  -d '{"message":"Посмотри, что я недавно прочитал, и предложи три похожие книги, которых ещё нет в моей библиотеке"}'
```

Детерминированные acceptance-тесты этого сценария используют fake-провайдер и
не требуют API key или сети.

### Frontend

Для frontend нужен Node.js 22.12 или новее:

```bash
cd frontend
npm install
npm run dev
```

Интерфейс будет доступен на `http://localhost:5173`.

### Тесты

```bash
cd backend
uv run pytest
```

Тесты не используют LLM или внешнюю сеть.

PostgreSQL-проверка создаёт и удаляет отдельную временную базу на локальном
сервере, поэтому запускается явно после старта контейнера:

```bash
cd backend
TEST_POSTGRES_ADMIN_URL=postgresql+psycopg://book_agent:book_agent@localhost:5432/postgres \
  uv run pytest
```

Реальный Open Library не входит в основной suite. Отдельный smoke запускается
явно; увеличенный timeout относится только к этой ручной диагностике:

```bash
cd backend
OPEN_LIBRARY_TIMEOUT_SECONDS=15 RUN_OPEN_LIBRARY_SMOKE=1 \
  uv run pytest -m network
```

## Известные ограничения

Главное ограничение: `demo_user_id` — учебная подмена аутентификации. Сервис
нельзя публиковать для нескольких пользователей без настоящей identity,
авторизации и tenant isolation. Кроме того, agent loop синхронный, retrieval
лексический, внешний catalog fallback локальный, а raw run endpoint хранит и
возвращает полную рабочую историю. Полный список угроз, controls и остаточных
рисков находится в [docs/THREAT_MODEL.md](./docs/THREAT_MODEL.md).

В этой версии намеренно не используются:

- LangChain, LangGraph, CrewAI и другие агентные фреймворки;
- несколько взаимодействующих агентов;
- MCP;
- browser или computer automation;
- автономные фоновые задачи на часы;
- сложный planner;
- векторная база «для всей памяти»;
- self-reflection после каждого шага;
- автоматическое переписывание собственных промптов.

Решение оставить самописный линейный loop и измеримые условия его пересмотра
записаны в [ADR-001](./docs/adr/001-agent-orchestration.md).

## Уровни готовности

- **Backend MVP — этапы 1–5:** четыре сценария выполняются через API, результаты проверяются по состоянию БД.
- **Безопасный MVP — этап 6:** запись или опасное действие можно остановить и подтвердить без повторного исполнения.
- **Пользовательский MVP — этап 7:** сценарии доступны через React-интерфейс.
- **Расширенная версия — этапы 8–10:** внешний каталог, PostgreSQL, RAG, evals и полная трассировка.
- **Учебная ревизия — этап 11:** проверяемые границы, demo, baseline, threat model и ADR.

Таким образом, внешний каталог, PostgreSQL и RAG не блокируют первую законченную версию.

## Полезные материалы

Проект остаётся провайдер-независимым. Эти ссылки нужны для реализации первого OpenAI-адаптера и понимания общих паттернов:

- [Responses API: руководство по переходу и ключевым концепциям](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Построение агентов](https://developers.openai.com/api/docs/guides/agents)
- [Evals](https://developers.openai.com/api/docs/guides/evals)
- [OpenAI developer resources: learning track по агентам](https://developers.openai.com/resources)

Документация API меняется. Перед реализацией конкретного адаптера следует повторно проверить актуальную схему официального SDK и endpoint, не перенося провайдерские детали в общий контракт.

## Главный учебный принцип

Качество агента определяется не только моделью. Надёжность создают строгие инструменты, ограниченный цикл, проверяемое состояние, approvals, идемпотентность, тесты и наблюдаемость. Именно эту систему вокруг модели и предстоит построить.
