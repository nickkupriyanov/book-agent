# Архитектура Book Agent

Это актуальная карта системы. Стрелка означает «зависит от».

```text
React UI ──HTTP──> FastAPI routes
                      │
                      ├──> AgentService ──> LLMProvider <── DeepSeekProvider
                      │         │
                      │         ├──> ToolRegistry ──> tool handlers
                      │         │                       │
                      │         │                       ├──> BookService
                      │         │                       └──> MemoryService
                      │         └──> AgentRunRepository
                      │
                      ├──> BookService ──> BookRepository ──> SQLAlchemy
                      │         └──> BookCatalog <── local / resilient Open Library
                      └──> MemoryService ──> MemoryRepository ──> SQLAlchemy
```

## Слои и правила зависимостей

- `api.py` и `dependencies.py` — composition root. Только здесь HTTP связан с
  конкретными адаптерами, настройками и созданием сервисов.
- `agent/service.py` знает абстракцию `LLMProvider` и `ToolRegistry`, но не знает
  DeepSeek, OpenAI SDK и HTTP.
- `tools/` описывает строгие входы, выходы и policy. Handler вызывает прикладной
  сервис и не выполняет SQL.
- `service.py` и `memory/service.py` содержат прикладные правила. Репозитории
  изолируют SQLAlchemy, а catalog/provider — внешний источник книг.
- `llm/deepseek.py`, `catalog/open_library.py` и SQLAlchemy-репозитории —
  инфраструктурные адаптеры; зависимости направлены к контрактам, а не обратно.

Эти ограничения проверяет `tests/test_architecture_contracts.py`. Тест не
пытается стать универсальным линтером: он охраняет несколько важных границ
именно этого небольшого проекта.

## Границы доверия

1. Текст пользователя и сохранённые заметки недоверенные.
2. Ответ модели недоверенный до проверки имени tool и Pydantic-схемы аргументов.
3. Только зарегистрированный handler может обратиться к прикладному сервису.
4. `user_id` берётся на сервере и замыкается внутри handler; модель его не задаёт.
5. Destructive tool только создаёт `PendingAction`. Изменение БД выполняется
   после отдельного HTTP approval и повторной проверки владельца.
6. Ответ внешнего каталога валидируется адаптером до попадания в доменную модель.

## Write flow

```text
POST /api/agent/runs
  -> AgentService получает ответ LLMProvider
  -> ToolRegistry проверяет allowlist и аргументы
  -> handler вызывает BookService с серверным user_id
  -> BookRepository меняет БД и commit
  -> ToolResult сохраняется в AgentRun
  -> следующий вызов модели формирует финальный ответ
  -> AgentRunResponse возвращается клиенту
```

Для `remove_book` середина потока отличается:

```text
validated remove_book -> PendingAction -> WAITING_FOR_APPROVAL
POST .../approve -> проверка run + action + user + срока жизни
                  -> handler -> commit -> resume AgentService
```

Reject закрывает действие без вызова handler. Повторный approve/reject возвращает
уже сохранённый результат, поэтому один action не применяет изменение дважды.

## Read flow рекомендаций

Agent последовательно вызывает `get_user_library(status=finished)`, затем
`find_similar_books(source_book_ids=...)`. Рекомендации вычисляются сервисом по
пересечению тегов; модель объясняет уже полученный результат, но не является
источником книг или score.
