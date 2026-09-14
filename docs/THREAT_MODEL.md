# Threat model и известные ограничения

Документ описывает учебную версию Book Agent после этапа 11. Наличие controls
ниже не означает production readiness.

## Что защищаем

- библиотеку, статусы чтения, заметки и preferences пользователя;
- целостность agent runs, steps и pending actions;
- ключ LLM-провайдера и внутренние ошибки инфраструктуры;
- предсказуемость действий: только опубликованные tools и не более одного
  эффекта на одно подтверждение.

## Границы доверия

```text
браузер | HTTP API | agent loop | tool registry | services | database
                         |
                         +------ недоверенный LLM provider
                         +------ недоверенные fragments заметок
services | catalog adapter | недоверенный внешний Open Library
```

Текст пользователя, ответы модели, сохранённые заметки и внешний HTTP-ответ
считаются недоверенными. Tool registry, серверный `user_id`, сервисы и БД —
контролируемая часть приложения.

## Угрозы и существующие controls

| Угроза | Что уже сделано | Остаточный риск |
| --- | --- | --- |
| Модель вызывает произвольный код или SQL | Закрытый allowlist ToolRegistry; unknown tool отклоняется | Уязвимость внутри разрешённого handler всё ещё опасна |
| Модель подменяет пользователя | `user_id` отсутствует в tool schemas и задаётся сервером | `demo_user_id` не является аутентификацией |
| Лишние или неверные аргументы | Pydantic `extra=forbid`, типы и диапазоны | Семантически неверные, но валидные аргументы возможны |
| Prompt injection в заметке | Retrieval явный; fragment считается данными; safe trace скрывает content | Модель всё ещё может неверно интерпретировать вредный текст |
| Удаление без согласия | Destructive tool создаёт durable PendingAction; handler ждёт approve | Скомпрометированный пользовательский сеанс сможет подтвердить действие |
| Повтор approve | Idempotency key, optimistic version и сохранённый result | Нет общего idempotency protocol для всех write endpoints |
| Доступ к чужим данным | Repository queries фильтруют по `user_id`; чужой action даёт 404 | Нет реальной identity и проверки tenant на уровне БД |
| Утечка секрета в диагностике | Safe trace рекурсивно redacts secrets/content; provider errors нормализуются | Raw AgentRun содержит сообщения и tool results |
| Ошибка внешнего каталога | Схема адаптера, timeout/retry, cache и local fallback | Нет circuit breaker; in-memory cache не общий между процессами |
| Бесконечный или повторяющийся loop | Step budget и detector повторяющихся tool calls | Синхронный запрос удерживает worker до остановки |

## Известные функциональные ограничения

- Все HTTP-запросы работают от одного `demo_user_id`; регистрации, login,
  sessions, roles и tenant isolation нет.
- Agent loop выполняется синхронно внутри HTTP-request. Нет очереди, streaming,
  отмены, background worker и distributed lock между несколькими процессами.
- Approval поддерживает одну изолированную destructive операцию, но не общий
  transaction plan из нескольких зависимых действий.
- Локальный RAG использует совпадение слов, а не embeddings; перефразирование и
  смысловые синонимы могут не найти релевантную заметку.
- Safe trace годится для обычной диагностики, но из-за redaction может быть
  недостаточна для редкого сбоя модели. Нет отдельного защищённого audit-доступа
  к raw trace, retention policy и шифрования чувствительных данных.
- Fake evals проверяют код и известные сценарии, но не доказывают качество
  реальной модели. Один opt-in live run не даёт статистической уверенности.
- Open Library fallback и cache рассчитаны на один процесс; circuit breaker,
  rate-limit coordination и distributed cache отсутствуют.
- Нет production deployment, TLS termination, secret manager, monitoring,
  backups, disaster recovery и нагрузочного тестирования.

## Что делать перед реальным запуском

Минимальный следующий security слой — настоящая identity и сквозной tenant
context: аутентификация, авторизация на каждом endpoint, tenant-aware keys и
интеграционные тесты межпользовательской изоляции. Затем нужны политика хранения
raw traces, шифрование, audit access, rate limits и асинхронное выполнение.

Agent framework не закрывает эти риски автоматически. Он рассматривается только
после появления workflow-задачи из триггеров, записанных в ADR-001.
