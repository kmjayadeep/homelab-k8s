# ADR 0002: Use a local Pi runner for reviewed repository changes

- Status: Accepted; initial implementation available
- Date: 2026-08-29

## Context

Repository automation can shorten planning and implementation, but an unrestricted agent could expose secrets, mutate the cluster, bypass review, or publish incomplete work. Runs also need a durable audit trail without preserving private model reasoning or credentials.

## Decision

Use the Pi SDK in a local TypeScript runner under `automation/autonomous-agent/`. The runner uses existing `openai-codex` authentication and in-memory, role-isolated sessions. Repository instructions are loaded while project extensions, skills, and prompt templates are disabled. Reviewers are read-only; the implementer receives only path-confined repository tools in an isolated Git worktree and never receives a shell.

The orchestrator owns a fixed validation and Git API. It does not expose cluster, Vault, destructive Git, merge, force-push, branch deletion, or unrestricted host commands. Kubernetes validation is limited to `kustomize build` piped directly to `kubectl apply --dry-run=client -f -`. No remote mutation is allowed until an explicit, persisted human approval at the final gate. Publishing may push only the generated branch and may create, but never merge, a pull request targeting `main`.

Each stage has wall-clock, turn, review-iteration, artifact-size, and run-size limits. Planning, code, and GitOps governance require structured `approved` verdicts from fresh role sessions. The code reviewer must use a different model ID from the implementer.

Operational state stays in ignored `.agent-state/`. Safe, bounded artifacts are copied to `agent-runs/YYYY/MM/<run-id>/` only in the generated worktree. The implementation and run record enter `main` only if a human merges the pull request. Raw Pi sessions, hidden reasoning, provider payloads, command logs, environment dumps, secret values, and credentials are never committed.

## Consequences

- Runs are local, opt-in, bounded, independently reviewed, resumable at durable gates, and human-merged.
- Existing Pi/Codex authentication remains outside Git.
- Worktrees and generated branches are intentionally retained for manual inspection and cleanup.
- A missing validation tool is a failure, not silent success.
- The initial command allowlist is deliberately narrow; broad custom validation and unattended issue ingestion are not supported.
- Subscription usage may not provide meaningful cost, so token, turn, iteration, and wall-clock accounting are authoritative.

## Alternatives rejected

- Hosted or issue-triggered agents: too much untrusted input and credential exposure for the first version.
- Model-accessible shell: difficult to constrain safely for arbitrary repository content.
- Automatic merge or direct push to `main`: bypasses the required human review boundary.
- Raw session retention: conflicts with secret and private-reasoning safety.

## Implementation

The approved design and incremental acceptance criteria are in `plans/0002-autonomous-ai-agent.md`. Installation and operation are documented in `automation/autonomous-agent/README.md`; committed run records are documented in `agent-runs/README.md`.
