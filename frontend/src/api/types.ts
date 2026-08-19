export const AGENT_RUN_STATUSES = [
  'running',
  'waiting_for_approval',
  'completed',
  'failed',
  'step_limit_exceeded',
] as const

export type AgentRunStatus = (typeof AGENT_RUN_STATUSES)[number]

export type PendingActionStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'expired'

export interface AgentWorkingStateResponse {
  goal: string
  completed_actions: Array<Record<string, unknown>>
  initial_step_budget: number
  remaining_step_budget: number
}

export interface PendingActionResponse {
  id: string
  summary: string
  status: PendingActionStatus
  expires_at: string
}

export interface AgentStepResponse {
  step_number: number
  messages: Array<Record<string, unknown>>
  response: Record<string, unknown> | null
  tool_results: Array<Record<string, unknown>>
  error: string | null
  duration_ms: number
}

export interface AgentRunResponse {
  id: string
  status: AgentRunStatus
  user_message: string
  working_state: AgentWorkingStateResponse
  final_answer: string | null
  stop_reason: string | null
  error: string | null
  pending_action: PendingActionResponse | null
  steps: AgentStepResponse[]
}

export interface SafeTraceStep {
  stepNumber: number
  durationMs: number
  toolNames: string[]
  resultCount: number
}

export interface PendingAction {
  id: string
  summary: string
  expiresAt: number
}

export interface AgentRun {
  id: string
  status: AgentRunStatus
  finalAnswer: string | null
  pendingAction: PendingAction | null
  trace: SafeTraceStep[]
}

export type ApprovalDecision = 'approve' | 'reject'

export interface ApprovalResponse {
  action: Record<string, unknown>
  run: AgentRunResponse
  replayed: boolean
}

export interface ApprovalResult {
  run: AgentRun
  replayed: boolean
}
