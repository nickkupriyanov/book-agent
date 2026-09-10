import { AGENT_RUN_STATUSES, READING_STATUSES } from './types'
import type {
  AgentRun,
  AgentRunStatus,
  ApprovalResult,
  CatalogSearchTrace,
  LibraryEntry,
  PendingAction,
  ReadingStatus,
  SafeTraceStep,
} from './types'

export class ContractError extends Error {
  constructor(message = 'Сервер вернул неподдерживаемый формат запуска.') {
    super(message)
    this.name = 'ContractError'
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStatus(value: unknown): value is AgentRunStatus {
  return (
    typeof value === 'string' &&
    AGENT_RUN_STATUSES.some((status) => status === value)
  )
}

function isReadingStatus(value: unknown): value is ReadingStatus {
  return (
    typeof value === 'string' &&
    READING_STATUSES.some((status) => status === value)
  )
}

function visibleText(value: string): string {
  return value.replace(/[—–]/g, '-')
}

function parseServerDateTime(value: unknown): number {
  if (typeof value !== 'string') return NaN

  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
  return Date.parse(hasTimezone ? value : `${value}Z`)
}

function optionalString(value: unknown): string | null {
  if (value === null) return null
  if (typeof value === 'string') return visibleText(value)
  throw new ContractError()
}

function decodeToolNames(response: unknown): string[] {
  if (!isRecord(response)) return []

  const toolCalls = response.tool_calls
  if (!Array.isArray(toolCalls)) return []

  return toolCalls.flatMap((call) => {
    if (!isRecord(call) || typeof call.name !== 'string') return []
    return [visibleText(call.name.slice(0, 80))]
  })
}

function decodeCatalogSearches(value: unknown): CatalogSearchTrace[] {
  if (value === undefined) return []
  if (!Array.isArray(value)) throw new ContractError()

  return value.map((search) => {
    if (
      !isRecord(search) ||
      (search.source !== 'local' && search.source !== 'open_library') ||
      typeof search.degraded !== 'boolean' ||
      typeof search.cached !== 'boolean'
    ) {
      throw new ContractError()
    }
    return {
      source: search.source,
      degraded: search.degraded,
      cached: search.cached,
    }
  })
}

function decodePendingAction(value: unknown): PendingAction {
  if (!isRecord(value)) {
    throw new ContractError(
      'Сервер не прислал действие, ожидающее подтверждения.',
    )
  }

  const expiresAt = parseServerDateTime(value.expires_at)

  if (
    typeof value.id !== 'string' ||
    typeof value.summary !== 'string' ||
    value.summary.trim().length === 0 ||
    value.status !== 'pending' ||
    !Number.isFinite(expiresAt)
  ) {
    throw new ContractError(
      'Сервер вернул несогласованное действие для подтверждения.',
    )
  }

  return {
    id: value.id,
    summary: visibleText(value.summary),
    expiresAt,
  }
}

function decodeTraceStep(value: unknown): SafeTraceStep {
  if (!isRecord(value)) throw new ContractError()

  const stepNumber = value.step_number
  const durationMs = value.duration_ms
  const toolResults = value.tool_results

  if (
    !Number.isInteger(stepNumber) ||
    (stepNumber as number) < 1 ||
    !Number.isInteger(durationMs) ||
    (durationMs as number) < 0 ||
    !Array.isArray(toolResults)
  ) {
    throw new ContractError()
  }

  return {
    stepNumber: stepNumber as number,
    durationMs: durationMs as number,
    toolNames: decodeToolNames(value.response),
    resultCount: toolResults.length,
    catalogSearches: decodeCatalogSearches(value.catalog_searches),
  }
}

export function decodeAgentRunResponse(payload: unknown): AgentRun {
  if (!isRecord(payload)) throw new ContractError()

  if (!isStatus(payload.status)) {
    throw new ContractError(
      'Сервер вернул неподдерживаемое состояние запуска.',
    )
  }

  if (
    typeof payload.id !== 'string' ||
    typeof payload.user_message !== 'string' ||
    !isRecord(payload.working_state) ||
    !Array.isArray(payload.steps)
  ) {
    throw new ContractError()
  }

  return {
    id: payload.id,
    status: payload.status,
    userMessage: visibleText(payload.user_message),
    finalAnswer: optionalString(payload.final_answer),
    pendingAction:
      payload.status === 'waiting_for_approval'
        ? decodePendingAction(payload.pending_action)
        : null,
    trace: payload.steps.map(decodeTraceStep),
  }
}

export function decodeApprovalResponse(payload: unknown): ApprovalResult {
  if (!isRecord(payload) || typeof payload.replayed !== 'boolean') {
    throw new ContractError(
      'Сервер вернул неподдерживаемый результат подтверждения.',
    )
  }

  return {
    run: decodeAgentRunResponse(payload.run),
    replayed: payload.replayed,
  }
}

export function decodeLibraryResponse(payload: unknown): LibraryEntry[] {
  if (!Array.isArray(payload)) {
    throw new ContractError('Сервер вернул неподдерживаемый формат библиотеки.')
  }

  return payload.map((value) => {
    if (!isRecord(value) || !isRecord(value.book)) {
      throw new ContractError(
        'Сервер вернул неподдерживаемый формат библиотеки.',
      )
    }

    const book = value.book
    if (
      typeof book.id !== 'string' ||
      typeof book.title !== 'string' ||
      typeof book.author !== 'string' ||
      !Array.isArray(book.tags) ||
      !book.tags.every((tag) => typeof tag === 'string') ||
      !isReadingStatus(value.status) ||
      typeof value.created_at !== 'string' ||
      typeof value.updated_at !== 'string'
    ) {
      throw new ContractError(
        'Сервер вернул неподдерживаемый формат библиотеки.',
      )
    }

    return {
      bookId: book.id,
      title: visibleText(book.title),
      author: visibleText(book.author),
      status: value.status,
    }
  })
}
