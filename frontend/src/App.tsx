import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  ApiError,
  createAgentRun,
  getAgentRun,
  getLibrary,
  resolveAgentAction,
} from './api/client'
import type {
  AgentRun,
  AgentRunStatus,
  ApprovalDecision,
  LibraryEntry,
  PendingAction,
  ReadingStatus,
  SafeTraceStep,
} from './api/types'
import {
  forgetActiveRun,
  readActiveRunId,
  rememberActiveRun,
} from './active-run-storage'
import './App.css'

type ConversationEntry =
  | { id: string; role: 'user' | 'error'; text: string }
  | { id: string; role: 'run'; run: AgentRun }

interface RunPresentation {
  title: string
  description: string
}

interface DecisionState {
  entryId: string
  decision: ApprovalDecision
}

interface DecisionError {
  entryId: string
  message: string
}

const EXAMPLE_PROMPTS = [
  'Покажи книги, которые я сейчас читаю',
  'Найди «Дюну» и добавь в список на чтение',
]

const APPROVAL_DATE_FORMAT = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'long',
  timeStyle: 'short',
})
const MAX_TIMEOUT_MS = 2_147_483_647
const LIBRARY_WRITE_TOOLS = new Set([
  'add_book',
  'update_book_status',
  'remove_book',
])

const READING_STATUS_LABELS: Record<ReadingStatus, string> = {
  want_to_read: 'Хочу прочитать',
  reading: 'Читаю',
  finished: 'Прочитано',
}

const RUN_PRESENTATIONS: Record<AgentRunStatus, RunPresentation> = {
  running: {
    title: 'Запуск ещё выполняется',
    description: 'Сервер ещё не закончил обработку запуска.',
  },
  waiting_for_approval: {
    title: 'Нужно подтверждение',
    description:
      'Агент остановился перед действием, которое требует подтверждения.',
  },
  completed: {
    title: 'Запуск завершён',
    description: 'Агент выполнил запрос и подготовил финальный ответ.',
  },
  failed: {
    title: 'Запуск завершился с ошибкой',
    description: 'Агент остановился безопасно. Попробуйте повторить запрос.',
  },
  step_limit_exceeded: {
    title: 'Достигнут лимит шагов',
    description: 'Агент исчерпал допустимое количество шагов и остановился.',
  },
}

function shouldRefreshLibrary(run: AgentRun): boolean {
  if (run.status === 'running' || run.status === 'waiting_for_approval') {
    return false
  }

  return run.trace.some((step) =>
    step.toolNames.some((toolName) => LIBRARY_WRITE_TOOLS.has(toolName)),
  )
}

interface LibraryPanelProps {
  entries: LibraryEntry[]
  error: string | null
  isLoading: boolean
}

function LibraryPanel({ entries, error, isLoading }: LibraryPanelProps) {
  const titleId = useId()

  return (
    <section
      className="library-panel"
      aria-labelledby={titleId}
      aria-busy={isLoading}
      aria-live="polite"
    >
      <div className="library-panel__heading">
        <div>
          <p>Источник истины</p>
          <h2 id={titleId}>Моя библиотека</h2>
        </div>
        {!isLoading && !error ? <span>Книг: {entries.length}</span> : null}
      </div>
      {isLoading ? (
        <p className="library-panel__state" role="status">
          Загружаем библиотеку
        </p>
      ) : error ? (
        <p className="library-panel__state library-panel__error" role="alert">
          {error}
        </p>
      ) : entries.length === 0 ? (
        <p className="library-panel__state">В библиотеке пока нет книг.</p>
      ) : (
        <ul className="library-list">
          {entries.map((entry) => (
            <li key={entry.bookId}>
              <div>
                <h3>{entry.title}</h3>
                <p>{entry.author}</p>
              </div>
              <span data-status={entry.status}>
                {READING_STATUS_LABELS[entry.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function resultLabel(step: SafeTraceStep): string {
  if (step.toolNames.length === 0) return 'Результат tool не требовался'
  if (step.resultCount === 0) return 'Результат tool не получен'
  if (step.resultCount === 1) return 'Получен 1 результат tool'
  return `Получено результатов tool: ${step.resultCount}`
}

function catalogSearchLabel(
  search: SafeTraceStep['catalogSearches'][number],
): string {
  if (search.degraded) {
    return 'Источник: локальный резервный каталог. Результаты могут быть неполными.'
  }
  if (search.source === 'local') return 'Источник: локальный каталог.'
  if (search.cached) return 'Источник: Open Library (кэш).'
  return 'Источник: Open Library.'
}

function RunTrace({ steps }: { steps: SafeTraceStep[] }) {
  if (steps.length === 0) return null

  return (
    <details className="run-trace">
      <summary>Как работал агент: шагов {steps.length}</summary>
      <ol>
        {steps.map((step) => (
          <li key={step.stepNumber}>
            <div className="trace-step__heading">
              <strong>Шаг {step.stepNumber}</strong>
              <span>{step.durationMs} мс</span>
            </div>
            <p>
              {step.toolNames.length > 0
                ? `Tool: ${step.toolNames.join(', ')}`
                : 'Финальный ответ модели'}
            </p>
            <p>{resultLabel(step)}</p>
            {step.catalogSearches.map((search, index) => (
              <p
                className="trace-step__catalog"
                data-degraded={search.degraded}
                key={`${search.source}-${index}`}
              >
                {catalogSearchLabel(search)}
              </p>
            ))}
          </li>
        ))}
      </ol>
    </details>
  )
}

interface ApprovalCardProps {
  action: PendingAction
  decision: ApprovalDecision | null
  error: string | null
  isDeciding: boolean
  onDecision: (decision: ApprovalDecision) => void
}

function ApprovalCard({
  action,
  decision,
  error,
  isDeciding,
  onDecision,
}: ApprovalCardProps) {
  const titleId = useId()
  const summaryId = useId()
  const stateId = useId()
  const [isExpired, setIsExpired] = useState(
    () => action.expiresAt <= Date.now(),
  )

  useEffect(() => {
    let timeoutId: number | undefined

    function checkDeadline() {
      const remainingMs = action.expiresAt - Date.now()
      if (remainingMs <= 0) {
        setIsExpired(true)
        return
      }

      timeoutId = window.setTimeout(
        checkDeadline,
        Math.min(remainingMs, MAX_TIMEOUT_MS),
      )
    }

    checkDeadline()
    return () => {
      if (timeoutId !== undefined) window.clearTimeout(timeoutId)
    }
  }, [action.expiresAt])

  return (
    <section
      className="approval-card"
      aria-labelledby={titleId}
      aria-describedby={`${summaryId} ${stateId}`}
    >
      <p className="approval-card__label">Действие ещё не выполнено</p>
      <h3 id={titleId}>Требуется ваше решение</h3>
      <p className="approval-card__summary" id={summaryId}>
        {action.summary}
      </p>
      <p>До подтверждения библиотека не изменится.</p>
      <p className="approval-card__expiry" id={stateId} aria-live="polite">
        {isExpired ? (
          'Срок, указанный сервером, истёк. Backend проверит это при решении.'
        ) : (
          <>
            Подтвердить можно до{' '}
            <time dateTime={new Date(action.expiresAt).toISOString()}>
              {APPROVAL_DATE_FORMAT.format(action.expiresAt)}
            </time>
            .
          </>
        )}
      </p>
      {error ? (
        <p className="approval-card__error" role="alert">{error}</p>
      ) : null}
      <div className="approval-card__actions" aria-busy={isDeciding}>
        <button
          type="button"
          disabled={isDeciding}
          onClick={() => onDecision('approve')}
        >
          {decision === 'approve' ? 'Подтверждаем' : 'Подтвердить'}
        </button>
        <button
          type="button"
          className="approval-card__reject"
          disabled={isDeciding}
          onClick={() => onDecision('reject')}
        >
          {decision === 'reject' ? 'Отклоняем' : 'Отклонить'}
        </button>
      </div>
    </section>
  )
}

interface RunResultProps {
  run: AgentRun
  decision: ApprovalDecision | null
  decisionError: string | null
  isDeciding: boolean
  onDecision: (decision: ApprovalDecision) => void
}

function RunResult({
  run,
  decision,
  decisionError,
  isDeciding,
  onDecision,
}: RunResultProps) {
  const presentation = RUN_PRESENTATIONS[run.status]
  const answer =
    run.status === 'completed' && run.finalAnswer
      ? run.finalAnswer
      : presentation.description

  return (
    <article className="run-result" data-status={run.status}>
      <p className="message__role">Статус запуска</p>
      <h2>{presentation.title}</h2>
      <p>{answer}</p>
      {run.status === 'waiting_for_approval' && run.pendingAction ? (
        <ApprovalCard
          action={run.pendingAction}
          decision={decision}
          error={decisionError}
          isDeciding={isDeciding}
          onDecision={onDecision}
        />
      ) : null}
      <RunTrace steps={run.trace} />
    </article>
  )
}

function App() {
  const [restorationRunId] = useState(readActiveRunId)
  const [message, setMessage] = useState('')
  const [conversation, setConversation] = useState<ConversationEntry[]>([])
  const [isRestoring, setIsRestoring] = useState(restorationRunId !== null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [library, setLibrary] = useState<LibraryEntry[]>([])
  const [isLibraryLoading, setIsLibraryLoading] = useState(true)
  const [libraryError, setLibraryError] = useState<string | null>(null)
  const [decisionInFlight, setDecisionInFlight] =
    useState<DecisionState | null>(null)
  const [decisionError, setDecisionError] = useState<DecisionError | null>(null)
  const decisionLock = useRef(false)
  const libraryRequestId = useRef(0)

  const loadLibrary = useCallback(async () => {
    const requestId = ++libraryRequestId.current
    setIsLibraryLoading(true)
    setLibraryError(null)

    try {
      const entries = await getLibrary()
      if (requestId === libraryRequestId.current) setLibrary(entries)
    } catch (error) {
      if (requestId !== libraryRequestId.current) return
      setLibraryError(
        error instanceof Error
          ? error.message
          : 'Не удалось загрузить библиотеку. Попробуйте ещё раз.',
      )
    } finally {
      if (requestId === libraryRequestId.current) {
        setIsLibraryLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    void loadLibrary()
  }, [loadLibrary])

  useEffect(() => {
    if (restorationRunId === null) return

    const runId = restorationRunId
    let isCancelled = false

    async function restoreRun() {
      try {
        const run = await getAgentRun(runId)
        if (isCancelled) return

        rememberActiveRun(run)
        setConversation([
          { id: crypto.randomUUID(), role: 'user', text: run.userMessage },
          { id: crypto.randomUUID(), role: 'run', run },
        ])
        if (shouldRefreshLibrary(run)) void loadLibrary()
      } catch (error) {
        if (isCancelled) return

        if (error instanceof ApiError && error.status === 404) {
          forgetActiveRun()
          setConversation([])
        } else {
          setConversation([
            {
              id: crypto.randomUUID(),
              role: 'error',
              text:
                error instanceof Error
                  ? error.message
                  : 'Не удалось восстановить запуск. Начните новую сессию.',
            },
          ])
        }
      } finally {
        if (!isCancelled) setIsRestoring(false)
      }
    }

    void restoreRun()
    return () => {
      isCancelled = true
    }
  }, [loadLibrary, restorationRunId])

  async function submitMessage(rawMessage: string) {
    const trimmedMessage = rawMessage.trim()
    if (!trimmedMessage || isSubmitting || isRestoring) return

    setConversation((current) => [
      ...current,
      { id: crypto.randomUUID(), role: 'user', text: trimmedMessage },
    ])
    setMessage('')
    setIsSubmitting(true)

    try {
      const run = await createAgentRun(trimmedMessage)
      rememberActiveRun(run)
      setConversation((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'run', run },
      ])
      if (shouldRefreshLibrary(run)) void loadLibrary()
    } catch (error) {
      const text =
        error instanceof Error
          ? error.message
          : 'Не удалось выполнить запрос. Попробуйте ещё раз.'
      setConversation((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'error', text },
      ])
    } finally {
      setIsSubmitting(false)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void submitMessage(message)
  }

  async function handleDecision(
    entryId: string,
    run: AgentRun,
    decision: ApprovalDecision,
  ) {
    if (decisionLock.current || !run.pendingAction) return

    decisionLock.current = true
    setDecisionInFlight({ entryId, decision })
    setDecisionError(null)

    try {
      const result = await resolveAgentAction(
        run.id,
        run.pendingAction.id,
        decision,
      )
      rememberActiveRun(result.run)
      setConversation((current) =>
        current.map((entry) =>
          entry.id === entryId && entry.role === 'run'
            ? { ...entry, run: result.run }
            : entry,
        ),
      )
      if (shouldRefreshLibrary(result.run)) void loadLibrary()
    } catch (error) {
      setDecisionError({
        entryId,
        message:
          error instanceof Error
            ? error.message
            : 'Не удалось отправить решение. Попробуйте ещё раз.',
      })
    } finally {
      decisionLock.current = false
      setDecisionInFlight(null)
    }
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand-mark" aria-hidden="true">B</div>
        <div>
          <p>Личная библиотека</p>
          <h1>Book Agent</h1>
        </div>
      </header>

      <LibraryPanel
        entries={library}
        error={libraryError}
        isLoading={isLibraryLoading}
      />

      <section className="conversation" aria-label="Диалог с агентом">
        {isRestoring ? (
          <article className="restoration-state" role="status">
            <p className="empty-state__label">Возвращаемся к сессии</p>
            <h2>Восстанавливаем запуск</h2>
            <p>Проверяем его актуальное состояние на сервере.</p>
          </article>
        ) : conversation.length === 0 ? (
          <div className="empty-state">
            <p className="empty-state__label">Новая сессия</p>
            <h2>Что найдём в библиотеке?</h2>
            <p>
              Попросите найти книгу, изменить статус чтения или подобрать
              следующую.
            </p>
            <div className="prompt-list" aria-label="Примеры запросов">
              {EXAMPLE_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  disabled={isSubmitting || isRestoring}
                  onClick={() => void submitMessage(prompt)}
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="message-list" aria-live="polite">
            {conversation.map((entry) =>
              entry.role === 'run' ? (
                <RunResult
                  key={entry.id}
                  run={entry.run}
                  decision={
                    decisionInFlight?.entryId === entry.id
                      ? decisionInFlight.decision
                      : null
                  }
                  decisionError={
                    decisionError?.entryId === entry.id
                      ? decisionError.message
                      : null
                  }
                  isDeciding={decisionInFlight !== null}
                  onDecision={(decision) =>
                    void handleDecision(entry.id, entry.run, decision)
                  }
                />
              ) : (
                <article
                  className={`message message--${entry.role}`}
                  key={entry.id}
                >
                  <p className="message__role">
                    {entry.role === 'user' ? 'Вы' : 'Ошибка'}
                  </p>
                  <p>{entry.text}</p>
                </article>
              ),
            )}
            {isSubmitting ? (
              <article className="message message--loading" role="status">
                <p className="message__role">Агент</p>
                <div className="loading-lines">
                  <span />
                  <span />
                  <span className="visually-hidden">Выполняю запрос</span>
                </div>
              </article>
            ) : null}
          </div>
        )}
      </section>

      <form className="composer" onSubmit={handleSubmit}>
        <label htmlFor="agent-message">Сообщение агенту</label>
        <div className="composer__row">
          <textarea
            id="agent-message"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Например: найди «Дюну»"
            rows={2}
            disabled={isSubmitting || isRestoring}
          />
          <button
            type="submit"
            disabled={
              isSubmitting || isRestoring || message.trim().length === 0
            }
          >
            {isSubmitting ? 'Отправляем' : 'Отправить'}
          </button>
        </div>
      </form>
    </main>
  )
}

export default App
