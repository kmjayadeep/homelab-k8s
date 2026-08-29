# Plan 0002: Local autonomous AI agent with reviewed pull requests

- Status: Approved for incremental implementation
- Date: 2026-08-29
- Target runtime: Local workstation
- Orchestrator: Pi SDK
- Model provider: OpenAI through `openai-codex`
- Related future ADR: `adrs/0002-autonomous-repository-agent.md`

## Goal

Build a local, resumable AI-agent runner that accepts arbitrary repository requirements, plans and implements them through independently reviewed stages, pauses for explicit human approval, and only then commits, pushes, and opens a pull request.

Every run must leave a structured, secret-safe audit record under `agent-runs/`. The implementation and its run record are included in the same pull request, so a human merge places both on `main`. The runner must never merge a pull request or push directly to `main`.

## Decisions

1. Use the Pi SDK for orchestration, isolated sessions, model selection, tool control, and usage accounting.
2. Use models available from the existing `openai-codex` authentication. Do not add API keys or credentials to this repository.
3. Run locally only. GitHub Actions and unattended issue-triggered execution are out of scope for the first version.
4. Accept requirements from a file or an interactive editor. Avoid putting requirements in command arguments by default.
5. Permit arbitrary repository tasks, but not arbitrary host, cluster, Vault, or network operations.
6. Use fresh reviewer sessions and a different model ID from the implementer for code review.
7. Require structured reviewer verdicts. A stage advances only on an explicit `approved` verdict.
8. Bound every review loop, model call, and full run.
9. Pause before the first remote mutation. Commit, push, and pull-request creation require explicit human approval.
10. Commit structured intermediate artifacts, summaries, validations, and verdicts. Do not commit raw model sessions, hidden reasoning, credentials, environment values, or unbounded command output.
11. Include run history in the implementation pull request. A merge of that pull request is the only mechanism that places the history on `main`.

## Non-goals

- Automatically merging pull requests.
- Directly pushing to `main` before or after a merge.
- Applying or reconciling Kubernetes resources.
- Reading or writing Vault values, Kubernetes Secret values, or other plaintext credentials.
- Running as a hosted or scheduled service.
- Consuming untrusted GitHub issue or pull-request text automatically.
- Supporting non-OpenAI providers in the first version.
- Preserving private chain-of-thought or complete Pi/Codex transcripts in Git.

## Proposed workflow

```text
intake
  -> explore_and_plan
  -> plan_review <-> plan_revision
  -> implement
  -> deterministic_validation
  -> code_review <-> implementation_fix
  -> documentation_impact_and_update
  -> governance_review <-> governance_fix
  -> final_validation
  -> awaiting_human_approval
  -> commit_and_push
  -> create_pull_request
  -> record_pull_request_metadata
  -> completed
```

A run that reaches a limit or an unrecoverable error moves to `failed`. A human may reject a run or leave it pending without making remote changes. Pending and failed runs must be resumable where safe.

## Initial limits

Use configuration with these defaults:

```yaml
limits:
  planReviewIterations: 3
  implementationReviewIterations: 4
  governanceReviewIterations: 2
  maxAgentTurnsPerStage: 20
  stageTimeoutMinutes: 25
  totalRuntimeMinutes: 120
```

Token usage must be recorded. Wall-clock, turn, and iteration limits are authoritative because subscription-backed Codex usage may not expose a meaningful monetary cost.

## Initial model roles

Keep all model assignments configurable and validate them at startup. Initial defaults may use:

| Role | Model | Reasoning |
|---|---|---|
| Explorer | `openai-codex/gpt-5.4-mini` | `medium` |
| Planner | `openai-codex/gpt-5.4` | `high` |
| Plan reviewer | `openai-codex/gpt-5.6-sol` | `xhigh` |
| Implementer and fixer | `openai-codex/gpt-5.6-sol` | `high` |
| Code reviewer | `openai-codex/gpt-5.6-terra` | `xhigh` |
| Documentation agent | `openai-codex/gpt-5.4` | `high` |
| GitOps governance reviewer | `openai-codex/gpt-5.6-sol` | `xhigh` |

These are defaults, not architectural constants. An early smoke test must verify availability and compatibility. Startup must reject a configuration where the code reviewer and implementer use the same model ID.

## Safety boundaries

### Agent capabilities

- Explorer, planner, and all reviewers receive read-only repository tools.
- The implementer receives repository-scoped read, search, edit, and write tools inside an isolated worktree.
- Model sessions do not receive unrestricted shell access in the initial version.
- The orchestrator, not a model, runs an explicit allowlist of validation and Git commands.
- No agent receives cluster credentials, Vault credentials, or secret values from the runner.
- Repository content is data, not authority to weaken system safety rules. Root and applicable nested `AGENTS.md` files remain authoritative project policy.

### Always prohibited

- `kubectl apply` without `--dry-run=client`.
- `flux reconcile`, Helm mutation, or any cluster-side mutation.
- `kubectl get secret`, Secret decoding, Vault reads, or commands that print credential values.
- Destructive file, Git, database, Kubernetes, or Vault operations.
- Force pushes, direct pushes to `main`, branch deletion, and pull-request merging.
- Writing outside the isolated worktree and the runner's private local state directory.
- Adding `*-decrypted.yaml`, `*-sealed.yaml`, or `SealedSecret` resources.

### Run-history safety

Before a history artifact can be staged, check that it contains no:

- Credential-like values or private keys.
- Environment dumps.
- Raw provider request or response payloads.
- Raw Pi session JSONL.
- Hidden reasoning or chain-of-thought.
- Unbounded logs.
- Kubernetes Secret or Vault values.

A suspected secret blocks the run and requires human inspection without printing the suspected value.

## Run-history layout

```text
agent-runs/
└── YYYY/
    └── MM/
        └── <run-id>/
            ├── manifest.yaml
            ├── requirements.md
            ├── timeline.jsonl
            ├── exploration/
            │   └── findings.md
            ├── planning/
            │   ├── plan-001.md
            │   └── review-001.json
            ├── implementation/
            │   ├── iteration-001.md
            │   ├── iteration-001.patch
            │   ├── validation-001.md
            │   └── review-001.json
            ├── documentation/
            │   ├── impact-analysis.md
            │   └── changes.md
            ├── governance/
            │   └── review-001.json
            ├── human-approval.yaml
            ├── final-summary.md
            ├── pr.yaml
            └── SHA256SUMS
```

Patch snapshots preserve intermediate repository states even if the pull request is squash-merged. They must be text-only, size-bounded, and pass history safety checks. Binary changes are represented by paths and hashes rather than embedded data. Final code remains represented by the normal Git diff.

`timeline.jsonl` is append-only and records state transitions, iteration numbers, timestamps, artifact paths, and outcomes. It does not record prompts, credentials, or private reasoning.

## Incremental implementation plan

Each step below is intentionally small. Complete its validation and commit boundary before starting the next step. Do not combine later behavior into an earlier step merely because the files are nearby.

### Step 1: Record the architecture and repository rules

Create the architectural and policy foundation before executable automation.

Changes:

- Add `adrs/0002-autonomous-repository-agent.md`.
- Add `agent-runs/README.md` describing the committed audit format and prohibited content.
- Update `AGENTS.md` with autonomous-run safety, history, validation, and PR rules.
- Add a short local-agent section to `README.md` that points to the ADR and runner documentation.

Validation:

- Confirm the ADR status and consequences match this plan.
- Confirm all referenced paths exist or are explicitly marked as future work.
- Search the documentation for any instruction permitting direct pushes, automatic merges, cluster mutation, or secret reads; none may remain.
- Run `git diff --check`.

Completion criterion:

- The security and trust boundaries are reviewable without reading implementation code.

### Step 2: Scaffold a local CLI with no model or Git mutations

Create `automation/autonomous-agent/` as an isolated Node.js/TypeScript package.

Changes:

- Add package metadata, lockfile, TypeScript configuration, test runner, and lint/typecheck scripts.
- Add a CLI with `start`, `resume`, `status`, and `inspect` command parsing.
- Accept requirements using `--requirements-file` and an interactive editor path.
- Add configuration loading with documented defaults and strict schema validation.
- Do not call Pi, modify Git, or create branches in this step.

Validation:

- Install dependencies from the lockfile.
- Run typechecking, unit tests, and linting.
- Verify malformed configuration and missing requirement files fail with non-zero status and concise errors.
- Verify requirements are not printed unless the user explicitly runs `inspect`.

Completion criterion:

- The CLI can parse and validate a run request without invoking a model or modifying the repository.

### Step 3: Implement durable run state and append-only artifacts

Build persistence before adding agent behavior.

Changes:

- Define versioned schemas for the manifest, timeline events, reviewer verdicts, human approval, and PR metadata.
- Create run IDs and the `agent-runs/YYYY/MM/<run-id>/` structure.
- Use atomic writes for mutable state and append-only writes for timeline events.
- Add legal state-transition enforcement.
- Add `resume`, `status`, and `inspect` behavior against fixture runs.
- Keep in-progress local state separate from committable history when it contains operational details that should not enter Git.

Validation:

- Unit-test every valid state transition and representative invalid transitions.
- Simulate interruption between writes and verify resume finds the last complete state.
- Verify unknown schema versions fail safely.
- Verify two processes cannot mutate the same run concurrently.
- Run typechecking, tests, linting, and `git diff --check`.

Completion criterion:

- A fake run can progress, stop, and resume deterministically without any model calls.

### Step 4: Add history sanitization and intermediate-state snapshots

Protect Git history before storing agent output.

Changes:

- Add bounded artifact writers for Markdown, JSON, JSONL, and patch files.
- Add redaction/blocking checks for private keys, credential patterns, environment dumps, forbidden filenames, and secret-resource content.
- Store hashes and metadata for binary changes instead of binary patches.
- Generate `SHA256SUMS` over committed run artifacts.
- Add an explicit maximum size per artifact and per run.

Validation:

- Use synthetic fake secrets only; never read real credentials into tests or agent context.
- Verify fake private keys, tokens, decrypted filenames, and `SealedSecret` manifests are blocked.
- Verify findings report only file, rule, and location metadata, not the matched value.
- Verify oversized and binary artifacts are handled as designed.
- Verify checksums are stable and detect modified fixtures.

Completion criterion:

- No unvalidated model or command output can be written to the committable history tree.

### Step 5: Add a Pi/Codex session adapter behind a fakeable interface

Integrate models without yet implementing the workflow.

Changes:

- Wrap Pi SDK session creation, model resolution, timeouts, turn limits, cancellation, and usage accounting.
- Use existing `openai-codex` authentication through Pi's model runtime.
- Load applicable repository instructions without loading arbitrary project extensions.
- Define structured terminating tools for planner output and reviewer verdicts.
- Keep sessions in memory and exclude raw session files from run history.
- Provide a deterministic fake adapter for all tests.

Validation:

- Unit-test timeout, cancellation, malformed structured output, unavailable models, and usage aggregation with the fake adapter.
- Verify startup rejects identical implementer and code-reviewer model IDs.
- Run an explicit opt-in read-only smoke test that asks each configured model for a small structured response.
- Confirm the smoke test creates no repository changes and records no authentication material.

Completion criterion:

- The runner can obtain validated structured output from each configured role without granting write access.

### Step 6: Implement exploration, planning, and the plan-review loop

Add the first useful end-to-end workflow while keeping the repository read-only.

Changes:

- Create role prompts for repository exploration, planning, and plan review.
- Give exploration and planning sessions read-only tools only.
- Require plans to include goals, non-goals, requirement traceability, files, small implementation steps, validation, risks, documentation impact, and rollback considerations.
- Require reviewers to return `approved` or `request_changes` with typed findings.
- Feed findings back to the planner until approved or the configured limit is reached.
- Persist every plan version and verdict through the safe artifact writer.

Validation:

- Test immediate approval, one revision, iteration exhaustion, timeout, and malformed verdict paths using the fake adapter.
- Run a read-only live scenario against a harmless documentation requirement.
- Confirm no tracked repository files outside the run history change.
- Confirm every plan-review iteration appears in the timeline and manifest.

Completion criterion:

- A requirement can produce an approved, auditable plan or stop safely without implementation.

### Step 7: Add isolated worktree creation and repository-scoped implementation

Introduce file mutation only after planning is reliable.

Changes:

- Verify the source checkout is on the configured base branch and has no unrelated changes before starting a mutable run.
- Create a uniquely named local branch and isolated Git worktree through orchestrator-owned commands.
- Give the implementer read/search/edit/write access only inside that worktree.
- Prevent writes through symlinks or resolved paths outside the worktree.
- Provide the implementer with the requirements, approved plan, applicable instructions, and prior findings.
- Capture a bounded summary and safe patch snapshot for each implementation iteration.
- Do not automatically remove worktrees or branches; cleanup is a separate human operation.

Validation:

- Test dirty checkout, branch collision, path traversal, symlink escape, outside-worktree write, and interrupted worktree creation.
- Verify the fake implementer can modify an allowed fixture and cannot modify a protected external fixture.
- Confirm no remote Git operation occurs.
- Run typechecking, tests, linting, and `git diff --check`.

Completion criterion:

- An approved plan can be implemented locally in isolation without shell or remote access from the model.

### Step 8: Add deterministic validation discovery and execution

Make objective checks a required gate before model review.

Changes:

- Add an explicit command allowlist and argument construction without shell interpolation.
- Always run `git diff --check` and the runner's own relevant tests.
- Discover changed Kustomizations and run `kustomize build` followed by `kubectl apply --dry-run=client -f -` where applicable.
- Add checks for forbidden secret artifacts and `SealedSecret` resources.
- Bound and sanitize command output before persistence or reviewer use.
- Record unavailable tools and skipped checks as visible failures or human-reviewed exceptions, not silent success.

Validation:

- Unit-test command selection and changed-Kustomization discovery.
- Test passing, failing, timed-out, missing-tool, and oversized-output commands.
- Verify generated commands cannot omit client dry-run or add cluster mutation flags.
- Validate a known application Kustomization without applying it.
- Confirm validation records contain results and metadata but no secret values.

Completion criterion:

- Implementation cannot reach code review unless all required deterministic checks pass or an explicit policy-defined exception is recorded.

### Step 9: Implement the code-review and fix loop

Add independent review of the actual diff.

Changes:

- Start each code review in a fresh read-only session using a different model ID from the implementer.
- Provide requirements, approved plan, current diff, deterministic validation summary, and prior finding resolutions.
- Require typed blocking and non-blocking findings with file locations where available.
- Route blocking findings to the implementer, rerun validation, capture a new patch snapshot, and review again.
- Stop on approval or iteration exhaustion.

Validation:

- Test immediate approval, multiple fix rounds, recurring findings, iteration exhaustion, and reviewer failure with the fake adapter.
- Verify every blocking finding has a later resolution or remains visible in the failed final summary.
- Verify reviewers cannot mutate files.
- Run a live harmless fixture task and inspect its complete review artifacts.

Completion criterion:

- No implementation advances with unresolved blocking code-review findings.

### Step 10: Add documentation impact and specialized governance review

Implement the repository-specific final review stages.

Changes:

- Add a documentation-impact stage that decides whether `README.md`, ADRs, plans, runbooks, or `AGENTS.md` require updates.
- Do not require an ADR for every task; require an explicit reason for creating, updating, or omitting one.
- Add a GitOps governance reviewer focused on Kubernetes conventions, Flux/Kustomize structure, Vault/ESO policy, secret safety, probes, resources, labels, ingress TLS, and prohibited cluster mutations.
- Route blocking governance findings back to the appropriate implementation or documentation stage.
- Rerun deterministic validation after fixes.

Validation:

- Test changes requiring no docs, README changes, ADR changes, and `AGENTS.md` changes.
- Test representative governance rejections for a `SealedSecret`, broad `ClusterSecretStore`, missing resource limits, and unsafe Vault handling using synthetic fixtures.
- Verify the governance reviewer remains read-only.
- Verify iteration exhaustion blocks human approval.

Completion criterion:

- Code, documentation, architecture, and repository-specific safety are all explicitly approved.

### Step 11: Add final validation, summary, and the resumable human gate

Stop safely before remote changes.

Changes:

- Rerun all deterministic checks against the final worktree.
- Generate a final summary covering requirements, changed files, decisions, validation, reviewer iterations, resolved findings, remaining risks, skipped checks, and model usage.
- Present `approve`, `request revisions`, `inspect`, `reject`, and `leave pending` choices.
- Persist the decision and timestamp without storing credentials or unnecessary personal host metadata.
- Route revision feedback back through implementation, validation, and review.
- Make `resume <run-id>` restore the pending approval state safely.

Validation:

- Test every human choice and resume path.
- Verify `approve` is impossible unless all gates are green and history safety checks pass.
- Verify rejection and pending exit perform no commit, push, or PR mutation.
- Verify human feedback is treated as requirements and does not bypass review.

Completion criterion:

- A complete run can pause indefinitely before any remote mutation and resume without losing its audit trail.

### Step 12: Add commit, push, and pull-request creation after approval

Add remote mutation last.

Changes:

- Build a conventional commit message and PR body from structured run artifacts.
- Stage only the approved implementation and safe run-history files.
- Show the exact staged paths and proposed commit/PR metadata before final confirmation.
- Commit and push the generated branch without force.
- Create a pull request with `gh`; never merge it.
- Write `pr.yaml`, then create and push a small metadata commit so the open PR contains its own URL and number.
- Make every operation idempotent and resumable after partial failure.
- Explicitly refuse a target branch other than the configured generated branch.

Validation:

- Use a fake Git/GitHub adapter to test commit failure, push failure, authentication failure, duplicate PR detection, PR creation failure, and metadata-commit retry.
- Verify no Git mutation occurs before recorded human approval.
- Verify force flags, merge commands, direct `main` pushes, and branch deletion are impossible through the adapter API.
- Perform one explicitly approved end-to-end test using a harmless documentation-only change and inspect the PR manually.

Completion criterion:

- An approved run creates a reviewable PR containing both the implementation and complete safe run history, while merge remains exclusively human-controlled.

### Step 13: Harden, document, and declare the first version complete

Finish with failure-oriented testing and operational documentation.

Changes:

- Document installation, Pi/Codex authentication prerequisites, configuration, starting, resuming, inspecting, rejecting, and manually cleaning local worktrees.
- Add tests for prompt injection from repository files, malformed model output, cancellation, process crashes, concurrent runs, large diffs, and history tampering.
- Add a compatibility check for the supported Pi SDK version and configured Codex models.
- Add a release checklist and troubleshooting section.
- Update the ADR implementation status.

Validation:

- Run the complete unit and integration suite from a clean checkout.
- Run typechecking, linting, dependency audit, and `git diff --check`.
- Validate all changed Kustomizations with client dry-run where applicable.
- Execute one read-only planning run and one explicitly approved documentation-only PR run.
- Review committed history to confirm it contains intermediate states but no raw sessions, hidden reasoning, or sensitive values.

Completion criterion:

- The local runner is documented, bounded, resumable, independently reviewed, and safe enough for opt-in use on arbitrary repository tasks.

## Validation policy for all steps

At every step:

1. Run the narrowest relevant unit tests first.
2. Run package-wide typechecking, tests, and linting.
3. Run `git diff --check`.
4. Build and client-dry-run every affected Kustomization.
5. Inspect changed and untracked paths for forbidden secret artifacts.
6. Report unavailable validation tools and remaining risks.
7. Do not apply, reconcile, commit, push, or create a PR unless that specific action belongs to the current approved step.

## Final acceptance criteria

- Requirements can be supplied without placing them in shell history by default.
- Every role uses an isolated session with an explicit model and tool policy.
- Planning, code, and governance loops require structured approval and have hard limits.
- Deterministic validation runs before every review and before human approval.
- The runner can stop and resume at safe boundaries.
- No model has unrestricted shell, cluster, Vault, or remote Git access.
- No commit, push, or PR is created before explicit human approval.
- The runner cannot merge or push directly to `main`.
- The PR contains requirements, intermediate plans, verdicts, safe implementation snapshots, validation summaries, final summary, and PR metadata.
- Merging the PR places both implementation and run history on `main`.
- Raw sessions, hidden reasoning, plaintext secrets, and unbounded logs never enter Git.
