import { decodeAgentRunResponse, decodeApprovalResponse } from './decode'
import type {
  AgentRun,
  ApprovalDecision,
  ApprovalResult,
} from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function createAgentRun(message: string): Promise<AgentRun> {
  let response: Response

  try {
    response = await fetch('/api/agent/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    })
  } catch {
    throw new ApiError(
      'Не удалось связаться с сервером. Проверьте, запущен ли backend.',
      0,
    )
  }

  if (!response.ok) {
    throw new ApiError(
      'Сервер не смог обработать запрос. Попробуйте ещё раз.',
      response.status,
    )
  }

  return decodeAgentRunResponse(await response.json())
}

export async function getAgentRun(runId: string): Promise<AgentRun> {
  let response: Response

  try {
    response = await fetch(`/api/agent/runs/${encodeURIComponent(runId)}`)
  } catch {
    throw new ApiError(
      'Не удалось восстановить запуск. Проверьте, запущен ли backend.',
      0,
    )
  }

  if (!response.ok) {
    throw new ApiError(
      'Сервер не смог восстановить запуск. Начните новую сессию.',
      response.status,
    )
  }

  return decodeAgentRunResponse(await response.json())
}

function approvalError(status: number): ApiError {
  if (status === 409) {
    return new ApiError(
      'Это решение уже принято или состояние запуска изменилось.',
      status,
    )
  }
  if (status === 410) {
    return new ApiError(
      'Срок подтверждения истёк. Обновите состояние запуска.',
      status,
    )
  }
  return new ApiError(
    'Сервер не смог принять решение. Попробуйте ещё раз.',
    status,
  )
}

export async function resolveAgentAction(
  runId: string,
  actionId: string,
  decision: ApprovalDecision,
): Promise<ApprovalResult> {
  let response: Response

  try {
    response = await fetch(
      `/api/agent/runs/${encodeURIComponent(runId)}/actions/${encodeURIComponent(actionId)}/${decision}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      },
    )
  } catch {
    throw new ApiError(
      'Не удалось связаться с сервером. Решение не отправлено.',
      0,
    )
  }

  if (!response.ok) throw approvalError(response.status)

  return decodeApprovalResponse(await response.json())
}
