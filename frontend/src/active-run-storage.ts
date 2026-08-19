import type { AgentRun } from './api/types'

export const ACTIVE_RUN_STORAGE_KEY = 'book-agent:active-run'

interface StoredActiveRun {
  version: 1
  runId: string
}

function removeStoredRun(): void {
  try {
    window.localStorage.removeItem(ACTIVE_RUN_STORAGE_KEY)
  } catch {
    // Storage may be unavailable; the backend remains the source of truth.
  }
}

export function readActiveRunId(): string | null {
  let rawValue: string | null

  try {
    rawValue = window.localStorage.getItem(ACTIVE_RUN_STORAGE_KEY)
  } catch {
    return null
  }

  if (rawValue === null) return null

  try {
    const value: unknown = JSON.parse(rawValue)
    if (
      typeof value === 'object' &&
      value !== null &&
      !Array.isArray(value) &&
      Object.keys(value).length === 2 &&
      'version' in value &&
      value.version === 1 &&
      'runId' in value &&
      typeof value.runId === 'string' &&
      value.runId.length > 0
    ) {
      return value.runId
    }
  } catch {
    // Invalid JSON is handled like any other unsupported stored value.
  }

  removeStoredRun()
  return null
}

export function rememberActiveRun(run: AgentRun): void {
  if (run.status === 'running' || run.status === 'waiting_for_approval') {
    const value: StoredActiveRun = { version: 1, runId: run.id }
    try {
      window.localStorage.setItem(
        ACTIVE_RUN_STORAGE_KEY,
        JSON.stringify(value),
      )
    } catch {
      // The current tab still works when persistent browser storage is blocked.
    }
    return
  }

  if (readActiveRunId() === run.id) removeStoredRun()
}

export function forgetActiveRun(): void {
  removeStoredRun()
}
