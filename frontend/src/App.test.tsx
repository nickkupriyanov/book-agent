import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { AgentRunResponse, AgentRunStatus } from './api/types'

const RUN_ID = 'c79f4bf2-448d-4eab-aa02-cfefac2f1f51'
const ACTION_ID = '43de88e6-8366-475a-9bd1-f33240e7059d'
const PENDING_ACTION = {
  id: ACTION_ID,
  summary: 'Удалить «Дюну» из вашей библиотеки.',
  status: 'pending' as const,
  expires_at: '2035-05-20T10:30:00',
}

function makeRun(
  overrides: Partial<AgentRunResponse> = {},
): AgentRunResponse {
  return {
    id: RUN_ID,
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

function jsonResponse(payload: unknown, status = 201): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function makeApprovalResponse(run: AgentRunResponse, replayed = false) {
  return {
    action: { status: 'approved' },
    run,
    replayed,
  }
}

async function submitMessage() {
  const user = userEvent.setup()
  render(<App />)

  await user.type(screen.getByLabelText('Сообщение агенту'), 'Найди Дюну')
  await user.click(screen.getByRole('button', { name: 'Отправить' }))
  return user
}

async function submitResponse(payload: unknown) {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    jsonResponse(payload),
  )
  await submitMessage()
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
        pending_action: status === 'waiting_for_approval' ? PENDING_ACTION : null,
      }),
    )

    expect(await screen.findByText(title)).toBeVisible()
  })

  it('shows a pending action without exposing identifiers or arguments', async () => {
    await submitResponse({
      ...makeRun({ status: 'waiting_for_approval' }),
      pending_action: {
        ...PENDING_ACTION,
        arguments: { book_id: 'secret-book-id' },
        idempotency_key: 'secret-idempotency-key',
      },
    })

    const card = await screen.findByRole('region', {
      name: 'Требуется ваше решение',
    })
    expect(within(card).getByText(PENDING_ACTION.summary)).toBeVisible()
    expect(within(card).getByText('До подтверждения библиотека не изменится.'))
      .toBeVisible()
    expect(card).toHaveTextContent(/Подтвердить можно до/)
    expect(card.querySelector('time')).toHaveAttribute(
      'datetime',
      '2035-05-20T10:30:00.000Z',
    )
    expect(within(card).getByRole('button', { name: 'Подтвердить' })).toBeEnabled()
    expect(within(card).getByRole('button', { name: 'Отклонить' })).toBeEnabled()
    expect(document.body).not.toHaveTextContent(RUN_ID)
    expect(document.body).not.toHaveTextContent(ACTION_ID)
    expect(document.body).not.toHaveTextContent('secret-book-id')
    expect(document.body).not.toHaveTextContent('secret-idempotency-key')
  })

  it('shows a controlled error when a waiting run has no pending action', async () => {
    await submitResponse(
      makeRun({ status: 'waiting_for_approval', pending_action: null }),
    )

    expect(
      await screen.findByText(
        'Сервер не прислал действие, ожидающее подтверждения.',
      ),
    ).toBeVisible()
  })

  it('marks an elapsed client deadline only as a hint', async () => {
    await submitResponse(
      makeRun({
        status: 'waiting_for_approval',
        pending_action: {
          ...PENDING_ACTION,
          expires_at: '2000-01-01T00:00:00Z',
        },
      }),
    )

    expect(
      await screen.findByText(
        'Срок, указанный сервером, истёк. Backend проверит это при решении.',
      ),
    ).toBeVisible()
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
  })

  it('approves once with an empty body and replaces the waiting run', async () => {
    const completed = makeRun({
      status: 'completed',
      final_answer: 'Книга удалена из библиотеки.',
      pending_action: null,
    })
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        jsonResponse(
          makeRun({
            status: 'waiting_for_approval',
            final_answer: null,
            pending_action: PENDING_ACTION,
          }),
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(makeApprovalResponse(completed, true), 200),
      )
    const user = await submitMessage()

    await user.click(
      await screen.findByRole('button', { name: 'Подтвердить' }),
    )

    expect(await screen.findByText('Книга удалена из библиотеки.')).toBeVisible()
    expect(screen.queryByText(PENDING_ACTION.summary)).not.toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledTimes(2)
    expect(fetchSpy).toHaveBeenLastCalledWith(
      `/api/agent/runs/${RUN_ID}/actions/${ACTION_ID}/approve`,
      expect.objectContaining({ method: 'POST', body: '{}' }),
    )
  })

  it('rejects through its own endpoint and keeps the resumed answer', async () => {
    const completed = makeRun({
      status: 'completed',
      final_answer: 'Книга осталась в библиотеке.',
      pending_action: null,
    })
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        jsonResponse(
          makeRun({
            status: 'waiting_for_approval',
            final_answer: null,
            pending_action: PENDING_ACTION,
          }),
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(makeApprovalResponse(completed), 200),
      )
    const user = await submitMessage()

    await user.click(await screen.findByRole('button', { name: 'Отклонить' }))

    expect(await screen.findByText('Книга осталась в библиотеке.')).toBeVisible()
    expect(fetchSpy).toHaveBeenCalledTimes(2)
    expect(fetchSpy.mock.calls[1]?.[0]).toBe(
      `/api/agent/runs/${RUN_ID}/actions/${ACTION_ID}/reject`,
    )
  })

  it('blocks both decisions and ignores a double click', async () => {
    let finishApproval: (response: Response) => void = () => undefined
    const approvalResponse = new Promise<Response>((resolve) => {
      finishApproval = resolve
    })
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        jsonResponse(
          makeRun({
            status: 'waiting_for_approval',
            final_answer: null,
            pending_action: PENDING_ACTION,
          }),
        ),
      )
      .mockReturnValueOnce(approvalResponse)
    const user = await submitMessage()
    const approve = await screen.findByRole('button', { name: 'Подтвердить' })

    await user.dblClick(approve)

    expect(fetchSpy).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('button', { name: 'Подтверждаем' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Отклонить' })).toBeDisabled()
    expect(screen.getByText(PENDING_ACTION.summary)).toBeVisible()

    finishApproval(
      jsonResponse(
        makeApprovalResponse(
          makeRun({
            status: 'completed',
            final_answer: 'Решение принято.',
            pending_action: null,
          }),
        ),
        200,
      ),
    )
    expect(await screen.findByText('Решение принято.')).toBeVisible()
  })

  it.each([
    [409, 'Это решение уже принято или состояние запуска изменилось.'],
    [410, 'Срок подтверждения истёк. Обновите состояние запуска.'],
  ])('keeps the pending card after a controlled %s error', async (status, message) => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        jsonResponse(
          makeRun({
            status: 'waiting_for_approval',
            final_answer: null,
            pending_action: PENDING_ACTION,
          }),
        ),
      )
      .mockResolvedValueOnce(jsonResponse({ detail: 'internal detail' }, status))
    const user = await submitMessage()

    await user.click(
      await screen.findByRole('button', { name: 'Подтвердить' }),
    )

    expect(await screen.findByText(message)).toBeVisible()
    expect(screen.getByText(PENDING_ACTION.summary)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Подтвердить' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Отклонить' })).toBeEnabled()
    expect(screen.queryByText('internal detail')).not.toBeInTheDocument()
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
