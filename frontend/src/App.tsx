import { useState } from 'react'
import type { FormEvent } from 'react'
import { createAgentRun } from './api/client'
import type { AgentRunResponse } from './api/types'
import './App.css'

interface ConversationEntry {
  id: string
  role: 'user' | 'assistant' | 'error'
  text: string
}

const EXAMPLE_PROMPTS = [
  'Покажи книги, которые я сейчас читаю',
  'Найди «Дюну» и добавь в список на чтение',
]

function completedAnswer(run: AgentRunResponse): string {
  if (run.status === 'completed' && run.final_answer) {
    return run.final_answer
  }

  return 'Запуск остановился без финального ответа.'
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
      {
        id: crypto.randomUUID(),
        role: 'user',
        text: trimmedMessage,
      },
    ])
    setMessage('')
    setIsSubmitting(true)

    try {
      const run = await createAgentRun(trimmedMessage)
      setConversation((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          text: completedAnswer(run),
        },
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
            {conversation.map((entry) => (
              <article
                className={`message message--${entry.role}`}
                key={entry.id}
              >
                <p className="message__role">
                  {entry.role === 'user'
                    ? 'Вы'
                    : entry.role === 'error'
                      ? 'Ошибка'
                      : 'Агент'}
                </p>
                <p>{entry.text}</p>
              </article>
            ))}
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
