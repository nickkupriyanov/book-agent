import { useState } from 'react'
import type { FormEvent } from 'react'
import { createAgentRun } from './api/client'
import type { AgentRun, AgentRunStatus, SafeTraceStep } from './api/types'
import './App.css'

type ConversationEntry =
  | { id: string; role: 'user' | 'error'; text: string }
  | { id: string; role: 'run'; run: AgentRun }

interface RunPresentation {
  title: string
  description: string
}

const EXAMPLE_PROMPTS = [
  'Покажи книги, которые я сейчас читаю',
  'Найди «Дюну» и добавь в список на чтение',
]

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

function resultLabel(step: SafeTraceStep): string {
  if (step.toolNames.length === 0) return 'Результат tool не требовался'
  if (step.resultCount === 0) return 'Результат tool не получен'
  if (step.resultCount === 1) return 'Получен 1 результат tool'
  return `Получено результатов tool: ${step.resultCount}`
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
          </li>
        ))}
      </ol>
    </details>
  )
}

function RunResult({ run }: { run: AgentRun }) {
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
      <RunTrace steps={run.trace} />
    </article>
  )
}

function App() {
  const [message, setMessage] = useState('')
  const [conversation, setConversation] = useState<ConversationEntry[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function submitMessage(rawMessage: string) {
    const trimmedMessage = rawMessage.trim()
    if (!trimmedMessage || isSubmitting) return

    setConversation((current) => [
      ...current,
      { id: crypto.randomUUID(), role: 'user', text: trimmedMessage },
    ])
    setMessage('')
    setIsSubmitting(true)

    try {
      const run = await createAgentRun(trimmedMessage)
      setConversation((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'run', run },
      ])
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

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand-mark" aria-hidden="true">B</div>
        <div>
          <p>Личная библиотека</p>
          <h1>Book Agent</h1>
        </div>
      </header>

      <section className="conversation" aria-label="Диалог с агентом">
        {conversation.length === 0 ? (
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
                  disabled={isSubmitting}
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
                <RunResult key={entry.id} run={entry.run} />
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
            disabled={isSubmitting}
          />
          <button
            type="submit"
            disabled={isSubmitting || message.trim().length === 0}
          >
            {isSubmitting ? 'Отправляем' : 'Отправить'}
          </button>
        </div>
      </form>
    </main>
  )
}

export default App
