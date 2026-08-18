import { AGENT_RUN_STATUSES } from './types'
import type {
  AgentRun,
  AgentRunStatus,
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

function optionalString(value: unknown): string | null {
  if (value === null) return null
  if (typeof value === 'string') return value.replace(/[—–]/g, '-')
  throw new ContractError()
}

function decodeToolNames(response: unknown): string[] {
  if (!isRecord(response)) return []

  const toolCalls = response.tool_calls
  if (!Array.isArray(toolCalls)) return []

  return toolCalls.flatMap((call) => {
    if (!isRecord(call) || typeof call.name !== 'string') return []
    return [call.name.slice(0, 80).replace(/[—–]/g, '-')]
  })
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
    finalAnswer: optionalString(payload.final_answer),
    trace: payload.steps.map(decodeTraceStep),
  }
}
