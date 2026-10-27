# Plan 0021: GitOps agent that opens pull requests

- Status: Active (PR open 2026-10-27; waits for the GitHub token)
- Owner: Jayadeep KM
- Related: [plan 0019](0019-kagent-deployment.md), [plan 0020](0020-kagent-sre-agent.md), [ADR 0001](../adrs/0001-vault-external-secrets.md), [ADR 0002](../adrs/0002-autonomous-repository-agent.md)

## Goal and scope

Add a second kagent agent, `homelab-gitops`, whose only way to change the cluster is a pull request against `kmjayadeep/homelab-k8s`. It reads the repository and the live cluster, writes complete files on a `kagent/<slug>` branch and opens a PR for human review. It never merges, never pushes to `main`, never deletes files and has no cluster write access. `homelab-sre` can delegate to it when the user explicitly asks for a PR, so "open a PR for that" works from Telegram.

Also in scope, because agent-written PRs need a mechanical check: a GitHub Actions workflow that runs `kustomize build` plus `kubeconform` on every Kustomize entry point for pull requests touching `clusters/`. It applies to Renovate PRs too.

Out of scope: merging, cluster writes, changes to other repositories, and GitHub issues.

## Starting state and prerequisites

Verified 2026-10-27:

- `main` has no branch protection and no rulesets. The operator pushes directly to `main` (35 of the last 40 non-merge commits), Renovate and `fluxcdbot` (Flux image automation over the SSH deploy key) also commit to it. A ruleset requiring PRs would need bypasses for the repository admin and deploy keys.
- The repository had no CI checks on PRs.
- kmcp is installed with kagent (`MCPServer` CRD `kagent.dev/v1alpha1`); it runs stdio MCP servers behind its HTTP proxy with `deployment.image/cmd/args/secretRefs`.
- GitHub MCP server `ghcr.io/github/github-mcp-server:v2.0.3` (2026-10-21) runs as `stdio`, supports `--toolsets`, `--tools`, `--exclude-tools`, `--read-only`, and takes `GITHUB_PERSONAL_ACCESS_TOKEN`. With `--toolsets=repos,pull_requests` it registers 29 tools; the write tools are `create_branch`, `create_or_update_file`, `push_files`, `create_pull_request`, `update_pull_request`, `update_pull_request_branch`, `merge_pull_request`, `pull_request_review_write`, `add_comment_to_pending_review`, `add_reply_to_pull_request_comment`, `delete_file`, `create_repository`, `fork_repository`. The image runs as root by default; it is a static binary and runs as 65532.
- kagent supports an agent as a tool (`type: Agent`) and per-tool filtering (`toolNames`).
- Vault: `services/github/kagent-gitops` is granted to the `kagent` role (homelab-iac `da3e445`, applied). The App values are **not yet imported**.

Authentication (decided 2026-10-27): a **GitHub App** owned by the operator, installed only on `homelab-k8s` with Contents read/write, Pull requests read/write and Metadata read. The MCP server mints short-lived installation tokens from the App's private key (`GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY`), so no long-lived token exists, PRs are authored by the App's bot user, and the App is not an admin: a ruleset requiring pull requests on `main` (bypass: repository admin role and deploy keys) blocks it from `main` while the operator and Flux keep pushing. Vault path `services/github/kagent-gitops` holds `app_id`, `installation_id` and `private_key`; `import-github-kagent-gitops-app.sh` imports all three (PEM over stdin).

Rejected alternatives: a fine-grained token on the owner's account (acts as admin, cannot be blocked by rulesets) and a machine account (works, but a long-lived token and a second account to maintain).

Approvals: merging the PR (creates the MCPServer with a Secret-backed token and a write-capable agent); any later ruleset or token change.

## Steps and gates

### Step 1: Manifests and workflow (this repo, PR)

- `clusters/titania/apps/kagent/github-mcp.yaml`: ExternalSecret `kagent-github` (key `GITHUB_PERSONAL_ACCESS_TOKEN`), `MCPServer` `github-mcp` (`transportType: stdio`, image `v2.0.3`, `--toolsets=repos,pull_requests`, `--exclude-tools` removing merge, delete, fork, new-repo, review and branch-update tools at the server, non-root, read-only rootfs, 20m/64Mi–500m/256Mi).
- `clusters/titania/apps/kagent/agent-homelab-gitops.yaml`: `Agent` with the GitHub read tools plus `create_branch`, `push_files`, `create_or_update_file`, `create_pull_request`, `update_pull_request`; Kubernetes read tools for confirming live names; a prompt that encodes AGENTS.md (layout, Vault-only secrets, style, Renovate ownership of versions, docs rules), the read-before-write workflow, the `kagent/` branch rule, the commit and PR format, and hard limits.
- `agent-homelab-sre.yaml`: `type: Agent` tool `homelab-gitops` and a prompt rule to use it only on explicit request, never during alert investigations.
- `.github/workflows/validate.yaml`: on `pull_request` touching `clusters/`, build every `kustomization.yaml` under `apps/` and `infra/`, run `kubeconform -strict -ignore-missing-schemas` on the output and on the bootstrap files.

Gate (before merge): client and server dry-runs pass; the workflow runs green on this PR itself.

### Step 2: Token (operator)

Create the GitHub App (Settings → Developer settings → GitHub Apps → New: no webhook, permissions Contents read/write, Pull requests read/write, Metadata read; install on `homelab-k8s` only), generate a private key, then in `homelab-iac/vault-config`: `./import-github-kagent-gitops-app.sh <app_id> <installation_id> < app.pem` and delete the PEM file. Optionally add the ruleset on `main`. Merge the PR afterwards, or the MCPServer pod has no credentials and the Kustomization waits.

### Step 3: Validate (after merge)

- `MCPServer` `github-mcp` Ready, `Agent` `homelab-gitops` Accepted and Ready, `homelab-sre` re-rendered with the delegate tool.
- Ask `homelab-gitops` in the UI for a trivial, reversible change (for example a comment or README line in `clusters/titania/apps/kagent/`); confirm a `kagent/...` branch and a PR appear, the validation workflow runs on it, and the PR body has the required sections. Close or merge the PR by hand.
- From Telegram: ask `homelab-sre` to investigate something, then "open a PR for that"; confirm delegation produces one PR.
- Confirm that a direct push to `main` is not possible for the agent: the merge tool is absent (`tools/list` on the MCPServer) and, once the ruleset exists, a push to `main` by the App is rejected.

## Validation and rollback

- Rollback: revert the PR; Flux prunes the MCPServer, Agent and ExternalSecret; `homelab-sre` loses the delegate. Revoke the GitHub token and delete `services/github/kagent-gitops` after the consumer is gone. Open `kagent/*` branches and PRs are closed by hand.
- Risks:
  - Until a ruleset exists on `main`, only the excluded merge tool and the prompt keep the App from writing to `main`, and Flux deploys `main` within minutes. Add the ruleset (require PR; bypass admin role and deploy keys) soon after.
  - The agent writes whole files; a truncated file silently removes content. The PR diff and the validation workflow are the guards; the prompt requires reading before writing.
  - PR bodies and commits are visible publicly if the repository is public; the agent is told never to include secret values, and ESO paths are the only secret references in Git anyway.
  - Provider: file contents of the repository go to DeepSeek until the ModelConfig points at `qwen-intel`.

## Outcome

Pending.
