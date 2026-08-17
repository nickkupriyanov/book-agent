export type AgentRunStatus =
  | 'running'
  | 'waiting_for_approval'
  | 'completed'
  | 'failed'
  | 'step_limit_exceeded'

export interface AgentRunResponse {
  id: string
  status: AgentRunStatus
  final_answer: string | null
}
