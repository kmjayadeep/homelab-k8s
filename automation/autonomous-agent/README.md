# Local autonomous repository agent

A local, bounded Pi SDK runner plans, implements, validates, independently reviews, and prepares repository changes. It pauses before commit, push, or PR creation. It never merges or pushes to `main`.

## Prerequisites and installation

- Node.js 22.19 or newer
- `git`, `gh`, and existing Pi `openai-codex` authentication
- `kustomize` and `kubectl` when Kubernetes manifests change

```bash
cd automation/autonomous-agent
npm ci
npm run check
npm run build
node dist/cli.js smoke
```

Pi SDK `0.84.4` is pinned. `smoke` checks configured model availability without opening sessions or modifying the repository. Configure roles and limits in `config.yaml`; the implementer and code reviewer must use different model IDs. Credentials belong in Pi's normal user authentication store and must never be added here.

## Use

Keep the source checkout on a clean `main` branch. Prefer a requirements file or editor so requirements do not enter shell history:

```bash
node dist/cli.js start --requirements-file /private/path/requirement.md
node dist/cli.js start --editor
node dist/cli.js status <run-id>
node dist/cli.js inspect <run-id>
node dist/cli.js inspect <run-id> --artifact final-summary.md
node dist/cli.js resume <run-id> --decision pending
node dist/cli.js resume <run-id> --decision revise --feedback-file /private/path/feedback.md
node dist/cli.js resume <run-id> --decision reject
node dist/cli.js resume <run-id> --decision approve
```

`inspect --requirements` is the only normal command that prints requirements. Approval displays paths, commit title, and PR target and requires typing `yes`; `--yes` is available only when the explicit `--decision approve` invocation is itself the recorded human action.

## Safety and lifecycle

Model sessions are in-memory. Read-only roles have confined read/list/search tools; the implementer additionally has confined edit/write tools in a generated worktree. No model has shell, network, Git, cluster, or Vault tools. The orchestrator runs only fixed argument arrays—never shell interpolation—and treats missing checks as failure.

Local state is stored in `.agent-state/`; generated worktrees are siblings under `.agent-worktrees/`. The runner intentionally does not remove either. After manually confirming a run is no longer needed, a human may use standard `git worktree` and branch cleanup commands. Destructive cleanup is never automatic.

Failed records retain the last durable state. Human-gate and remote publication steps are idempotent where GitHub permits; inspect failures before retrying. Do not hand-edit state. A checksum mismatch, safety finding, unavailable model/tool, dirty checkout, repeated review rejection, malformed model result, timeout, or limit exhaustion blocks progress.

See `adrs/0002-autonomous-repository-agent.md`, `plans/0002-autonomous-ai-agent.md`, and `agent-runs/README.md`.

## Release checklist

1. Run `npm ci`, `npm run check`, `npm audit`, and `git diff --check` from a clean checkout.
2. Run `smoke` and a read-only planning fixture.
3. Validate every affected Kustomization with client dry-run.
4. Manually inspect a documentation-only test PR and its checksums.
5. Confirm no raw sessions, secret-like test values, or unbounded output entered Git.
