import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { AgentRunResponse, AgentRunStatus } from './api/types'

function makeRun(
  overrides: Partial<AgentRunResponse> = {},
): AgentRunResponse {
  return {
    id: 'c79f4bf2-448d-4eab-aa02-cfefac2f1f51',
    status: 'completed',
    user_message: 'Найди Дюну',
    working_state: {
      goal: 'Найди Дюну',
      completed_actions: [],
      initial_step_budget: 5,
      remaining_step_budget: 4,
    },
    final_answer: 'Нашёл «Дюну» — Фрэнк Герберт.',
    stop_reason: 'final_response',
    error: null,
    pending_action: null,
    steps: [],
    ...overrides,
  }
}

async function submitResponse(payload: unknown) {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status: 201,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  const user = userEvent.setup()
  render(<App />)

  await user.type(screen.getByLabelText('Сообщение агенту'), 'Найди Дюну')
  await user.click(screen.getByRole('button', { name: 'Отправить' }))
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Book Agent chat', () => {
  it('sends a message and preserves the completed scenario', async () => {
    await submitResponse(makeRun())

    expect(await screen.findByText('Запуск завершён')).toBeVisible()
    expect(screen.getByText('Нашёл «Дюну» - Фрэнк Герберт.')).toBeVisible()
    expect(screen.queryByText(/—/)).not.toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/agent/runs',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ message: 'Найди Дюну' }),
      }),
    )
  })

  it.each<[AgentRunStatus, string]>([
    ['running', 'Запуск ещё выполняется'],
    ['waiting_for_approval', 'Нужно подтверждение'],
    ['completed', 'Запуск завершён'],
    ['failed', 'Запуск завершился с ошибкой'],
    ['step_limit_exceeded', 'Достигнут лимит шагов'],
  ])('renders an explicit %s state', async (status, title) => {
    await submitResponse(
      makeRun({
        status,
        final_answer: status === 'completed' ? 'Готово.' : null,
      }),
    )

    expect(await screen.findByText(title)).toBeVisible()
  })

  it('renders only allowlisted trace fields', async () => {
    await submitResponse(
      makeRun({
        steps: [
          {
            step_number: 1,
            duration_ms: 37,
            messages: [{ content: 'secret system prompt' }],
            response: {
              text: 'hidden provider text',
              tool_calls: [
                {
                  name: 'search_books',
                  arguments: { token: 'secret argument' },
                },
              ],
            },
            tool_results: [{ output: 'secret tool output' }],
            error: 'internal exception details',
          },
        ],
      }),
    )

    expect(await screen.findByText('Как работал агент: шагов 1')).toBeVisible()
    expect(screen.getByText('Шаг 1')).toBeInTheDocument()
    expect(screen.getByText('37 мс')).toBeInTheDocument()
    expect(screen.getByText('Tool: search_books')).toBeInTheDocument()
    expect(screen.getByText('Получен 1 результат tool')).toBeInTheDocument()
    expect(screen.queryByText('secret system prompt')).not.toBeInTheDocument()
    expect(screen.queryByText('secret argument')).not.toBeInTheDocument()
    expect(screen.queryByText('secret tool output')).not.toBeInTheDocument()
    expect(screen.queryByText('internal exception details')).not.toBeInTheDocument()
  })

  it('shows a controlled contract error for an unknown status', async () => {
    await submitResponse({ ...makeRun(), status: 'paused_by_provider' })

    expect(
      await screen.findByText(
        'Сервер вернул неподдерживаемое состояние запуска.',
      ),
    ).toBeVisible()
  })

  it('leaves loading and shows a safe error when the API is unavailable', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('offline'))
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), 'Покажи библиотеку')
    await user.click(screen.getByRole('button', { name: 'Отправить' }))

    expect(
      await screen.findByText(
        'Не удалось связаться с сервером. Проверьте, запущен ли backend.',
      ),
    ).toBeVisible()
    await user.type(screen.getByLabelText('Сообщение агенту'), 'Повторить')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Отправить' })).toBeEnabled()
    })
    expect(screen.queryByText('Выполняю запрос')).not.toBeInTheDocument()
  })

  it('does not expose backend details from an HTTP error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'internal database failure' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), 'Покажи библиотеку')
    await user.click(screen.getByRole('button', { name: 'Отправить' }))

    expect(
      await screen.findByText(
        'Сервер не смог обработать запрос. Попробуйте ещё раз.',
      ),
    ).toBeVisible()
    expect(screen.queryByText('internal database failure')).not.toBeInTheDocument()
  })

  it('does not send an empty message', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), '   ')

    expect(screen.getByRole('button', { name: 'Отправить' })).toBeDisabled()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
