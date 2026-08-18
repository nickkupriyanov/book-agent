import { decodeAgentRunResponse } from './decode'
import type { AgentRun } from './types'

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
