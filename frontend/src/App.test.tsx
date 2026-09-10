import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ACTIVE_RUN_STORAGE_KEY } from './active-run-storage'
import type {
  AgentRunResponse,
  AgentRunStatus,
  LibraryEntryResponse,
} from './api/types'

const RUN_ID = 'c79f4bf2-448d-4eab-aa02-cfefac2f1f51'
const ACTION_ID = '43de88e6-8366-475a-9bd1-f33240e7059d'
const DUNE_ID = '10000000-0000-0000-0000-000000000001'
const NINETEEN_EIGHTY_FOUR_ID = '10000000-0000-0000-0000-000000000002'
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

function makeLibraryEntry(
  overrides: Partial<LibraryEntryResponse> = {},
): LibraryEntryResponse {
  return {
    book: {
      id: DUNE_ID,
      title: 'Дюна',
      author: 'Фрэнк Герберт',
      tags: ['science_fiction'],
    },
    status: 'reading',
    created_at: '2026-08-19T10:00:00Z',
    updated_at: '2026-08-19T10:00:00Z',
    ...overrides,
  }
}

function makeToolStep(stepNumber: number, ...toolNames: string[]) {
  return {
    step_number: stepNumber,
    messages: [],
    response: {
      tool_calls: toolNames.map((name, index) => ({
        id: `call-${stepNumber}-${index}`,
        name,
        arguments: {},
      })),
    },
    tool_results: toolNames.map((name, index) => ({
      tool_call_id: `call-${stepNumber}-${index}`,
      tool_name: name,
      output: {},
    })),
    error: null,
    duration_ms: 12,
  }
}

function jsonResponse(payload: unknown, status = 201): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

type MockReply = () => Response | Promise<Response>

function reply(payload: unknown, status = 201): MockReply {
  return () => jsonResponse(payload, status)
}

function rejected(error: Error): MockReply {
  return () => Promise.reject(error)
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.toString()
  return input.url
}

function mockApi(
  agentReplies: MockReply[] = [],
  libraryReplies: MockReply[] = [],
) {
  let agentIndex = 0
  let libraryIndex = 0

  return vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = requestUrl(input)
    if (url === '/api/library') {
      const libraryReply = libraryReplies[libraryIndex++] ?? reply([], 200)
      return Promise.resolve(libraryReply())
    }

    const agentReply = agentReplies[agentIndex++]
    if (!agentReply) {
      return Promise.reject(new Error(`Unexpected request: ${url}`))
    }
    return Promise.resolve(agentReply())
  })
}

function agentCalls(fetchSpy: ReturnType<typeof mockApi>) {
  return fetchSpy.mock.calls.filter(([input]) => requestUrl(input) !== '/api/library')
}

function libraryCalls(fetchSpy: ReturnType<typeof mockApi>) {
  return fetchSpy.mock.calls.filter(([input]) => requestUrl(input) === '/api/library')
}

function makeApprovalResponse(run: AgentRunResponse, replayed = false) {
  return {
    action: { status: 'approved' },
    run,
    replayed,
  }
}

async function submitMessage(message = 'Найди Дюну') {
  const user = userEvent.setup()
  render(<App />)

  await user.type(screen.getByLabelText('Сообщение агенту'), message)
  await user.click(screen.getByRole('button', { name: 'Отправить' }))
  return user
}

async function submitResponse(payload: unknown) {
  mockApi([reply(payload)])
  await submitMessage()
}

afterEach(() => {
  vi.restoreAllMocks()
  window.localStorage.clear()
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
    const fetchSpy = mockApi([
      reply(
        makeRun({
          status: 'waiting_for_approval',
          pending_action: {
            ...PENDING_ACTION,
            expires_at: '2000-01-01T00:00:00Z',
          },
        }),
      ),
    ])
    await submitMessage()

    expect(
      await screen.findByText(
        'Срок, указанный сервером, истёк. Backend проверит это при решении.',
      ),
    ).toBeVisible()
    expect(agentCalls(fetchSpy)).toHaveLength(1)
  })

  it('approves once with an empty body and replaces the waiting run', async () => {
    const completed = makeRun({
      status: 'completed',
      final_answer: 'Книга удалена из библиотеки.',
      pending_action: null,
    })
    const fetchSpy = mockApi([
      reply(
        makeRun({
          status: 'waiting_for_approval',
          final_answer: null,
          pending_action: PENDING_ACTION,
        }),
      ),
      reply(makeApprovalResponse(completed, true), 200),
    ])
    const user = await submitMessage()

    await user.click(
      await screen.findByRole('button', { name: 'Подтвердить' }),
    )

    expect(await screen.findByText('Книга удалена из библиотеки.')).toBeVisible()
    expect(screen.queryByText(PENDING_ACTION.summary)).not.toBeInTheDocument()
    expect(agentCalls(fetchSpy)).toHaveLength(2)
    expect(agentCalls(fetchSpy).at(-1)).toEqual([
      `/api/agent/runs/${RUN_ID}/actions/${ACTION_ID}/approve`,
      expect.objectContaining({ method: 'POST', body: '{}' }),
    ])
  })

  it('rejects through its own endpoint and keeps the resumed answer', async () => {
    const completed = makeRun({
      status: 'completed',
      final_answer: 'Книга осталась в библиотеке.',
      pending_action: null,
    })
    const fetchSpy = mockApi([
      reply(
        makeRun({
          status: 'waiting_for_approval',
          final_answer: null,
          pending_action: PENDING_ACTION,
        }),
      ),
      reply(makeApprovalResponse(completed), 200),
    ])
    const user = await submitMessage()

    await user.click(await screen.findByRole('button', { name: 'Отклонить' }))

    expect(await screen.findByText('Книга осталась в библиотеке.')).toBeVisible()
    expect(agentCalls(fetchSpy)).toHaveLength(2)
    expect(agentCalls(fetchSpy)[1]?.[0]).toBe(
      `/api/agent/runs/${RUN_ID}/actions/${ACTION_ID}/reject`,
    )
  })

  it('blocks both decisions and ignores a double click', async () => {
    let finishApproval: (response: Response) => void = () => undefined
    const approvalResponse = new Promise<Response>((resolve) => {
      finishApproval = resolve
    })
    const fetchSpy = mockApi([
      reply(
        makeRun({
          status: 'waiting_for_approval',
          final_answer: null,
          pending_action: PENDING_ACTION,
        }),
      ),
      () => approvalResponse,
    ])
    const user = await submitMessage()
    const approve = await screen.findByRole('button', { name: 'Подтвердить' })

    await user.dblClick(approve)

    expect(agentCalls(fetchSpy)).toHaveLength(2)
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
    mockApi([
      reply(
        makeRun({
          status: 'waiting_for_approval',
          final_answer: null,
          pending_action: PENDING_ACTION,
        }),
      ),
      reply({ detail: 'internal detail' }, status),
    ])
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

  it('shows allowlisted catalog source, cache, and fallback metadata', async () => {
    const user = userEvent.setup()
    await submitResponse(
      {
        ...makeRun(),
        steps: [
          {
            ...makeToolStep(1, 'search_books'),
            catalog_searches: [
              {
                source: 'open_library',
                degraded: false,
                cached: false,
                provider_payload: 'secret catalog payload',
              },
            ],
          },
          {
            ...makeToolStep(2, 'search_books'),
            catalog_searches: [
              {
                source: 'open_library',
                degraded: false,
                cached: true,
              },
            ],
          },
          {
            ...makeToolStep(3, 'search_books'),
            catalog_searches: [
              {
                source: 'local',
                degraded: true,
                cached: false,
              },
            ],
          },
        ],
      },
    )

    await user.click(await screen.findByText('Как работал агент: шагов 3'))

    expect(screen.getByText('Источник: Open Library.')).toBeVisible()
    expect(screen.getByText('Источник: Open Library (кэш).')).toBeVisible()
    expect(
      screen.getByText(
        'Источник: локальный резервный каталог. Результаты могут быть неполными.',
      ),
    ).toBeVisible()
    expect(document.body).not.toHaveTextContent('secret catalog payload')
  })

  it('rejects malformed catalog trace metadata', async () => {
    await submitResponse(
      {
        ...makeRun(),
        steps: [
          {
            ...makeToolStep(1, 'search_books'),
            catalog_searches: [
              {
                source: 'unknown_provider',
                degraded: 'false',
                cached: false,
              },
            ],
          },
        ],
      },
    )

    expect(
      await screen.findByText('Сервер вернул неподдерживаемый формат запуска.'),
    ).toBeVisible()
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
    mockApi([rejected(new TypeError('offline'))])
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
    mockApi([reply({ detail: 'internal database failure' }, 500)])
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
    const fetchSpy = mockApi()
    const user = userEvent.setup()
    render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), '   ')

    expect(screen.getByRole('button', { name: 'Отправить' })).toBeDisabled()
    expect(agentCalls(fetchSpy)).toHaveLength(0)
  })

  it('restores the same waiting run after a new render without creating one', async () => {
    const waitingRun = makeRun({
      status: 'waiting_for_approval',
      final_answer: null,
      pending_action: PENDING_ACTION,
    })
    const fetchSpy = mockApi([
      reply(waitingRun),
      reply(waitingRun, 200),
    ])
    const user = userEvent.setup()
    const firstRender = render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), 'Найди Дюну')
    await user.click(screen.getByRole('button', { name: 'Отправить' }))
    expect(await screen.findByText(PENDING_ACTION.summary)).toBeVisible()
    expect(window.localStorage.getItem(ACTIVE_RUN_STORAGE_KEY)).toBe(
      JSON.stringify({ version: 1, runId: RUN_ID }),
    )

    firstRender.unmount()
    render(<App />)

    expect(await screen.findByText(PENDING_ACTION.summary)).toBeVisible()
    expect(screen.getByText('Найди Дюну')).toBeVisible()
    expect(agentCalls(fetchSpy)).toHaveLength(2)
    expect(agentCalls(fetchSpy).at(-1)).toEqual([`/api/agent/runs/${RUN_ID}`])
    expect(agentCalls(fetchSpy).filter((call) => call[1]?.method === 'POST'))
      .toHaveLength(1)
  })

  it.each([
    ['corrupted JSON', '{broken'],
    ['an unsupported version', JSON.stringify({ version: 2, runId: RUN_ID })],
  ])('clears %s without calling the API', (_case, storedValue) => {
    window.localStorage.setItem(ACTIVE_RUN_STORAGE_KEY, storedValue)
    const fetchSpy = mockApi()

    render(<App />)

    expect(screen.getByText('Новая сессия')).toBeVisible()
    expect(window.localStorage.getItem(ACTIVE_RUN_STORAGE_KEY)).toBeNull()
    expect(agentCalls(fetchSpy)).toHaveLength(0)
  })

  it('clears a missing run and opens an empty session', async () => {
    window.localStorage.setItem(
      ACTIVE_RUN_STORAGE_KEY,
      JSON.stringify({ version: 1, runId: RUN_ID }),
    )
    const fetchSpy = mockApi([reply({ detail: 'not found' }, 404)])

    render(<App />)

    expect(screen.getByText('Восстанавливаем запуск')).toBeVisible()
    expect(await screen.findByText('Новая сессия')).toBeVisible()
    expect(window.localStorage.getItem(ACTIVE_RUN_STORAGE_KEY)).toBeNull()
    expect(agentCalls(fetchSpy)).toHaveLength(1)
  })

  it('shows a restored terminal run but no longer marks it unfinished', async () => {
    window.localStorage.setItem(
      ACTIVE_RUN_STORAGE_KEY,
      JSON.stringify({ version: 1, runId: RUN_ID }),
    )
    const fetchSpy = mockApi([reply(makeRun(), 200)])

    render(<App />)

    expect(await screen.findByText('Запуск завершён')).toBeVisible()
    expect(window.localStorage.getItem(ACTIVE_RUN_STORAGE_KEY)).toBeNull()
    expect(agentCalls(fetchSpy)).toContainEqual([`/api/agent/runs/${RUN_ID}`])
  })
})

describe('Library panel and MVP scenarios', () => {
  it('shows library loading independently from the chat', () => {
    mockApi([], [() => new Promise<Response>(() => undefined)])

    render(<App />)

    expect(screen.getByText('Загружаем библиотеку')).toBeVisible()
    expect(screen.getByText('Новая сессия')).toBeVisible()
    expect(screen.getByLabelText('Сообщение агенту')).toBeEnabled()
  })

  it('shows an empty library', async () => {
    mockApi()

    render(<App />)

    expect(await screen.findByText('В библиотеке пока нет книг.')).toBeVisible()
    expect(screen.getByText('Книг: 0')).toBeVisible()
  })

  it('shows books, authors, and every reading status', async () => {
    const entries = [
      makeLibraryEntry(),
      makeLibraryEntry({
        book: {
          id: NINETEEN_EIGHTY_FOUR_ID,
          title: '1984',
          author: 'Джордж Оруэлл',
          tags: ['dystopia'],
        },
        status: 'want_to_read',
      }),
      makeLibraryEntry({
        book: {
          id: '10000000-0000-0000-0000-000000000004',
          title: 'Atomic Habits',
          author: 'James Clear',
          tags: ['productivity'],
        },
        status: 'finished',
      }),
    ]
    mockApi([], [reply(entries, 200)])

    render(<App />)

    const panel = await screen.findByRole('region', { name: 'Моя библиотека' })
    expect(await within(panel).findByText('Дюна')).toBeVisible()
    expect(within(panel).getByText('Фрэнк Герберт')).toBeVisible()
    expect(within(panel).getByText('Читаю')).toBeVisible()
    expect(within(panel).getByText('Хочу прочитать')).toBeVisible()
    expect(within(panel).getByText('Прочитано')).toBeVisible()
    expect(within(panel).getByText('Книг: 3')).toBeVisible()
  })

  it('shows a library error without breaking the chat', async () => {
    mockApi([], [rejected(new TypeError('offline'))])

    render(<App />)

    expect(
      await screen.findByText(
        'Не удалось загрузить библиотеку. Проверьте соединение с backend.',
      ),
    ).toBeVisible()
    expect(screen.getByText('Новая сессия')).toBeVisible()
    expect(screen.getByLabelText('Сообщение агенту')).toBeEnabled()
  })

  it('passes the current-reading MVP without refreshing a read-only run', async () => {
    const run = makeRun({
      user_message: 'Покажи книги, которые я сейчас читаю',
      final_answer: 'Сейчас вы читаете «Дюну».',
      steps: [makeToolStep(1, 'get_user_library')],
    })
    const fetchSpy = mockApi(
      [reply(run)],
      [reply([makeLibraryEntry()], 200)],
    )

    await submitMessage('Покажи книги, которые я сейчас читаю')

    expect(await screen.findByText('Сейчас вы читаете «Дюну».')).toBeVisible()
    expect(screen.getByText('Дюна')).toBeVisible()
    expect(libraryCalls(fetchSpy)).toHaveLength(1)
  })

  it('passes the add-book MVP and confirms it with a fresh library GET', async () => {
    const addedDune = makeLibraryEntry({ status: 'want_to_read' })
    const run = makeRun({
      user_message: 'Найди Дюну и добавь в список на чтение',
      final_answer: 'Добавил «Дюну» в список.',
      steps: [
        makeToolStep(1, 'search_books'),
        makeToolStep(2, 'add_book'),
      ],
    })
    const fetchSpy = mockApi(
      [reply(run)],
      [reply([], 200), reply([addedDune], 200)],
    )

    await submitMessage('Найди Дюну и добавь в список на чтение')

    expect(await screen.findByText('Добавил «Дюну» в список.')).toBeVisible()
    const panel = screen.getByRole('region', { name: 'Моя библиотека' })
    expect(await within(panel).findByText('Дюна')).toBeVisible()
    expect(within(panel).getByText('Хочу прочитать')).toBeVisible()
    expect(libraryCalls(fetchSpy)).toHaveLength(2)
  })

  it('passes the status-change MVP and shows the backend value', async () => {
    const book = {
      id: NINETEEN_EIGHTY_FOUR_ID,
      title: '1984',
      author: 'Джордж Оруэлл',
      tags: ['dystopia'],
    }
    const reading = makeLibraryEntry({ book, status: 'reading' })
    const finished = makeLibraryEntry({ book, status: 'finished' })
    const run = makeRun({
      user_message: 'Я дочитал 1984. Отметь её как прочитанную',
      final_answer: 'Отметил «1984» как прочитанную.',
      steps: [
        makeToolStep(1, 'search_books'),
        makeToolStep(2, 'update_book_status'),
      ],
    })
    const fetchSpy = mockApi(
      [reply(run)],
      [reply([reading], 200), reply([finished], 200)],
    )

    await submitMessage('Я дочитал 1984. Отметь её как прочитанную')

    expect(await screen.findByText('Отметил «1984» как прочитанную.'))
      .toBeVisible()
    const panel = screen.getByRole('region', { name: 'Моя библиотека' })
    expect(await within(panel).findByText('Прочитано')).toBeVisible()
    expect(within(panel).queryByText('Читаю')).not.toBeInTheDocument()
    expect(libraryCalls(fetchSpy)).toHaveLength(2)
  })

  it('passes the recommendation MVP without mutating the library', async () => {
    const finishedDune = makeLibraryEntry({ status: 'finished' })
    const finished1984 = makeLibraryEntry({
      book: {
        id: NINETEEN_EIGHTY_FOUR_ID,
        title: '1984',
        author: 'Джордж Оруэлл',
        tags: ['dystopia'],
      },
      status: 'finished',
    })
    const run = makeRun({
      user_message: 'Предложи три похожие книги',
      final_answer:
        'Рекомендую «Пикник на обочине», «Цветы для Элджернона» и «Левую руку Тьмы».',
      steps: [
        makeToolStep(1, 'get_user_library'),
        makeToolStep(2, 'find_similar_books'),
      ],
    })
    const fetchSpy = mockApi(
      [reply(run)],
      [reply([finishedDune, finished1984], 200)],
    )

    await submitMessage('Предложи три похожие книги')

    expect(
      await screen.findByText(
        'Рекомендую «Пикник на обочине», «Цветы для Элджернона» и «Левую руку Тьмы».',
      ),
    ).toBeVisible()
    expect(screen.getByText('Книг: 2')).toBeVisible()
    expect(libraryCalls(fetchSpy)).toHaveLength(1)
  })

  it('does not invent a library change after a failed write run', async () => {
    const unchangedLibrary = [makeLibraryEntry()]
    const run = makeRun({
      status: 'failed',
      final_answer: null,
      steps: [makeToolStep(1, 'update_book_status')],
    })
    const fetchSpy = mockApi(
      [reply(run)],
      [reply(unchangedLibrary, 200), reply(unchangedLibrary, 200)],
    )

    await submitMessage('Отметь Дюну как прочитанную')

    expect(await screen.findByText('Запуск завершился с ошибкой')).toBeVisible()
    const panel = screen.getByRole('region', { name: 'Моя библиотека' })
    expect(within(panel).getByText('Читаю')).toBeVisible()
    expect(within(panel).queryByText('Прочитано')).not.toBeInTheDocument()
    expect(libraryCalls(fetchSpy)).toHaveLength(2)
  })
})

describe('Stage 7 acceptance and keyboard flow', () => {
  it('restores a pending action, approves it once, and refreshes the library', async () => {
    const waitingRun = makeRun({
      status: 'waiting_for_approval',
      final_answer: null,
      pending_action: PENDING_ACTION,
      steps: [makeToolStep(1, 'remove_book')],
    })
    const completedRun = makeRun({
      final_answer: 'Книга удалена из библиотеки.',
      steps: [makeToolStep(1, 'remove_book')],
    })
    const dune = makeLibraryEntry()
    const fetchSpy = mockApi(
      [
        reply(waitingRun),
        reply(waitingRun, 200),
        reply(makeApprovalResponse(completedRun), 200),
      ],
      [reply([dune], 200), reply([dune], 200), reply([], 200)],
    )
    const user = userEvent.setup()
    const firstRender = render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), 'Удали Дюну')
    await user.click(screen.getByRole('button', { name: 'Отправить' }))
    expect(await screen.findByText(PENDING_ACTION.summary)).toBeVisible()

    firstRender.unmount()
    render(<App />)
    await user.click(
      await screen.findByRole('button', { name: 'Подтвердить' }),
    )

    expect(await screen.findByText('Книга удалена из библиотеки.')).toBeVisible()
    expect(await screen.findByText('В библиотеке пока нет книг.')).toBeVisible()
    const approvalCalls = agentCalls(fetchSpy).filter(([input]) =>
      requestUrl(input).endsWith('/approve'),
    )
    expect(approvalCalls).toHaveLength(1)
    expect(libraryCalls(fetchSpy)).toHaveLength(3)
  })

  it('restores a pending action, rejects it once, and keeps the library', async () => {
    const waitingRun = makeRun({
      status: 'waiting_for_approval',
      final_answer: null,
      pending_action: PENDING_ACTION,
      steps: [makeToolStep(1, 'remove_book')],
    })
    const completedRun = makeRun({
      final_answer: 'Книга осталась в библиотеке.',
      steps: [makeToolStep(1, 'remove_book')],
    })
    const dune = makeLibraryEntry()
    const fetchSpy = mockApi(
      [
        reply(waitingRun),
        reply(waitingRun, 200),
        reply(makeApprovalResponse(completedRun), 200),
      ],
      [reply([dune], 200), reply([dune], 200), reply([dune], 200)],
    )
    const user = userEvent.setup()
    const firstRender = render(<App />)

    await user.type(screen.getByLabelText('Сообщение агенту'), 'Удали Дюну')
    await user.click(screen.getByRole('button', { name: 'Отправить' }))
    expect(await screen.findByText(PENDING_ACTION.summary)).toBeVisible()

    firstRender.unmount()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Отклонить' }))

    expect(await screen.findByText('Книга осталась в библиотеке.')).toBeVisible()
    const panel = screen.getByRole('region', { name: 'Моя библиотека' })
    expect(await within(panel).findByRole('heading', { name: 'Дюна' }))
      .toBeVisible()
    const rejectionCalls = agentCalls(fetchSpy).filter(([input]) =>
      requestUrl(input).endsWith('/reject'),
    )
    expect(rejectionCalls).toHaveLength(1)
    expect(libraryCalls(fetchSpy)).toHaveLength(3)
  })

  it('moves keyboard focus through both approval choices and the composer', async () => {
    const waitingRun = makeRun({
      status: 'waiting_for_approval',
      final_answer: null,
      pending_action: PENDING_ACTION,
    })
    window.localStorage.setItem(
      ACTIVE_RUN_STORAGE_KEY,
      JSON.stringify({ version: 1, runId: RUN_ID }),
    )
    mockApi([reply(waitingRun, 200)])
    const user = userEvent.setup()

    render(<App />)
    await screen.findByText(PENDING_ACTION.summary)

    await user.tab()
    expect(screen.getByRole('button', { name: 'Подтвердить' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Отклонить' })).toHaveFocus()
    await user.tab()
    expect(screen.getByLabelText('Сообщение агенту')).toHaveFocus()
  })

  it('focuses the native trace summary before the composer', async () => {
    const completedRun = makeRun({
      steps: [makeToolStep(1, 'get_user_library')],
    })
    window.localStorage.setItem(
      ACTIVE_RUN_STORAGE_KEY,
      JSON.stringify({ version: 1, runId: RUN_ID }),
    )
    mockApi([reply(completedRun, 200)])
    const user = userEvent.setup()

    render(<App />)
    const summary = await screen.findByText('Как работал агент: шагов 1')

    await user.tab()
    expect(summary).toHaveFocus()
    expect(summary.tagName).toBe('SUMMARY')
    await user.tab()
    expect(screen.getByLabelText('Сообщение агенту')).toHaveFocus()
  })
})
