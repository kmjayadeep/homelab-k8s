# Plan 0024: homelab-gitops as a coding agent

- Status: In progress 2026-10-29
- Owner: Jayadeep KM
- Related: [plan 0021](0021-kagent-gitops-agent.md), [plan 0023](0023-kagent-merge-policy.md), [ADR 0007](../adrs/0007-policy-gated-merges.md)

## Goal and scope

Give `homelab-gitops` a real editing loop instead of whole-file rewrites through the GitHub API: a local
copy of the repository, exact string edits, and the CI validators (`kustomize build`, `kubeconform`)
before anything is pushed. Authentication stays where it is: the GitHub App lives only in the
`github-mcp` server, and the agent keeps pushing branches and opening PRs through those MCP tools. The
agent pod gets no token, no kubeconfig and no new RBAC.

Out of scope: a gVisor `SandboxAgent` on Agent Substrate (not installed; single-tenant cluster) and a
BYO coding harness. Both remain the upgrade path if the skill-based agent proves too limited.

## Starting state and prerequisites

- kagent 0.10.4: `Agent.spec.skills.gitRefs` is in the installed CRD. A declarative agent with skills
  runs the `golang-adk:<version>-full` image (Wolfi, user 1001, bash, python3, node, curl, ripgrep,
  tar, sha256sum, diff; no git, kustomize, kubectl or helm) and gains the built-in `bash`,
  `read_file`, `write_file`, `edit_file` tools plus a skill tool that loads `SKILL.md`.
- Both repositories are public, so the skills-init container and the setup script need no credentials.
- The agent pod has no NetworkPolicy egress restriction (it already talks to GitHub via the MCP
  server); the `homelab-gitops` ServiceAccount has no RoleBindings.
- Evidence of the gap (2 days of logs): 95 raw fetches and 42 file-content reads for 6 pushes; no
  local validation; whole-file rewrites.

## Steps and gates

1. Skill `automation/kagent-skills/gitops-coder/` (this PR): `SKILL.md` plus `scripts/setup.sh`
   (pinned, checksum-verified kustomize v5.8.3 and kubeconform v0.7.0 into
   `$WORKSPACE/bin`; repository tarball of `main` into `$WORKSPACE/<repo>` with a pristine copy under
   `.orig/`), `validate.sh` (CI-equivalent build and schema check; kustomizations with remote git bases are skipped because the image has no git) and
   `changed.sh` (file list and diff). Removal safety: scripts only delete directories they created,
   recognised by a marker file, inside an absolute non-root `$WORKSPACE`. Gate: the three scripts run
   inside `golang-adk:0.10.4-full` as uid 1001 against the real repositories, including the refusal
   paths (`WORKSPACE=/`, bad ref, directory without marker) and a deliberately broken manifest.
2. Agent (this PR): `spec.skills.gitRefs` pointing at the skill path on `main`, an `emptyDir`
   workspace at `/workspace` (2Gi limit), `WORKSPACE` env, resources raised to 2 CPU / 1Gi for
   kustomize builds, and the system prompt's workflow rewritten around setup, local edit, validate,
   diff, then `push_files` with the workspace content and `create_pull_request`.
3. After merge: confirm the pod runs the `-full` image with the skills-init container; A2A dry task
   ("set up the workspace, validate `clusters/titania/apps/kagent`, report tool versions, no branch,
   no PR") to prove bash and the scripts; then a real small change request and check the PR diff is
   exact and the PR body carries the local validation result. Observe the tool mix in the logs over the
   following days (fewer `fetch`, `edit_file` present).

## Validation and rollback

- `kustomize build clusters/titania/apps/kagent | kubectl apply --dry-run=client -f -`; validation
  workflow on the PR.
- Rollback: revert the PR; the controller returns the agent to the plain `golang-adk` image. Nothing
  else changes (no new Secrets, RBAC or network rules).
- Risks: bash in the agent pod. Mitigated by what the pod does not have (no cluster credentials,
  no GitHub token, no RBAC), by the prompt's limits, by the ruleset on `main` and the merge policy
  (ADR 0007) on every `kagent/*` PR, and by the scripts' removal guards. The kagent API token the
  runtime mounts for its own controller calls is readable from bash; it is the agent's own identity
  and grants nothing beyond what the agent already does. Skills load at pod start, so a skill change
  needs a Deployment restart. Prompt injection through repository content now reaches a shell; the
  same content already reached the model before, and the shell has nothing to steal.

## Outcome

Pending.
