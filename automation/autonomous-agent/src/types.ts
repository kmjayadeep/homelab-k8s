export const states = [
  "intake", "explore_and_plan", "plan_review", "plan_revision", "implement",
  "deterministic_validation", "code_review", "implementation_fix",
  "documentation_impact_and_update", "governance_review", "governance_fix",
  "final_validation", "awaiting_human_approval", "commit_and_push",
  "create_pull_request", "record_pull_request_metadata", "completed", "failed", "rejected",
] as const;

export type RunState = (typeof states)[number];
export type Role = "explorer" | "planner" | "planReviewer" | "implementer" | "codeReviewer" | "documentation" | "governanceReviewer";
export type Reasoning = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

export interface ModelRole { model: string; reasoning: Reasoning }
export interface Limits {
  planReviewIterations: number;
  implementationReviewIterations: number;
  governanceReviewIterations: number;
  maxAgentTurnsPerStage: number;
  stageTimeoutMinutes: number;
  totalRuntimeMinutes: number;
  maxArtifactBytes: number;
  maxRunBytes: number;
}
export interface Config {
  schemaVersion: 1;
  baseBranch: string;
  branchPrefix: string;
  localStateDirectory: string;
  roles: Record<Role, ModelRole>;
  limits: Limits;
  validation: { extraCommands: Array<{ command: string; args: string[] }> };
}
export interface Usage { input: number; output: number; cacheRead: number; cacheWrite: number; turns: number }
export interface Manifest {
  schemaVersion: 1;
  runId: string;
  createdAt: string;
  updatedAt: string;
  state: RunState;
  baseBranch: string;
  branch?: string;
  worktree?: string;
  iterations: { plan: number; implementation: number; governance: number };
  usage: Usage;
  failure?: string;
}
export interface Finding { severity: "blocking" | "non_blocking"; message: string; file?: string; line?: number }
export interface Verdict { schemaVersion: 1; verdict: "approved" | "request_changes"; summary: string; findings: Finding[] }
export interface AgentResult { text: string; structured?: unknown; usage: Usage; humanInputs: string[] }
export interface AgentRequest {
  role: Role;
  cwd: string;
  system: string;
  prompt: string;
  writable: boolean;
  timeoutMs: number;
  maxTurns: number;
  interactive: boolean;
  onProgress?: (message: string) => void;
  onHumanInput?: (input: string) => Promise<void>;
}
export interface TimelineEvent { schemaVersion: 1; timestamp: string; from?: RunState; to: RunState; outcome: "started" | "succeeded" | "failed" | "paused"; iteration?: number; artifact?: string }
