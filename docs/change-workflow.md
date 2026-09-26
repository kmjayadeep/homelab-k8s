# Change workflow

Use this checklist for human or agent changes. [AGENTS.md](../AGENTS.md) takes precedence for safety; this page explains the documentation lifecycle and where to look.

## Before editing

1. Read the root README and AGENTS.md, then [the repository map](repository-map.md). Check `git status` and scope your task to the affected directory.
2. Follow the relevant bootstrap Flux Kustomization and Kustomize entry point. Read the nearby manifests and any linked docs, [ADRs](../adrs/README.md), or [plans](../plans/README.md). For Vault/ESO work, follow the additional required reading in AGENTS.md.
3. Identify whether the change can affect live resources, secrets, data, or reconciliation/pruning. Do not mutate the cluster or perform destructive changes without explicit approval. Reading repository files or running client dry-runs is not approval to deploy.

## Choose the right document

| Question | Destination |
| --- | --- |
| How does the current system work or how is it maintained? | `docs/<topic>.md` (or an app-local README for a tightly scoped component) |
| Why was a significant, durable trade-off chosen? | `adrs/NNNN-<topic>.md` using [the ADR template](../adrs/TEMPLATE.md) |
| What are we about to do, test, or roll back? | `plans/NNNN-<topic>.md` using [the plan template](../plans/TEMPLATE.md), only when multiple steps or significant risk justify it |
| Small routine manifest fix? | Change the manifest and any impacted docs; no ADR or plan required |

Numbers are unique **within each directory**, assigned from the next available number. ADR and plan numbers need not match. Do not rename existing files just to align them. Link related decisions and plans explicitly, using relative Markdown links within this repo. Links to the sibling IaC repo may be written as paths with an explicit note that it is a separate repository.

## Close the loop

- A plan is a working artifact, **not** a source of permanent policy. When a choice becomes durable, record its rationale and consequences in an ADR; put current operational instructions in `docs/` (or component-local docs). Link the resulting ADR from the plan and mark the plan Completed, Superseded, or Abandoned with the outcome. Do **not** move, delete, or overwrite cited historical plans; retain useful evidence and avoid duplicating lengthy logs in ADRs. Clean up an unreferenced draft only after explicit approval for deletion.
- ADRs are historical decision records. If a decision changes, add a new ADR and link it from the old one; do not rewrite old rationale to pretend the new decision was always in effect. Correct factual errors and mark superseded status with the replacement link. ADR status or plans alone do not prove a deployment happened.
- Update the relevant index (`docs/README.md`, `adrs/README.md`, or `plans/README.md`) for new pages, and update existing pointers when status changes. Avoid stale links and unverified claims about runtime state.

## Validate and report

For changed manifests, run `kustomize build <affected-entry-point> | kubectl apply --dry-run=client -f -` as required by AGENTS.md. A client dry-run can still depend on local tooling and cluster discovery; report failures, not a guessed pass. Review the build output **without exposing secret values**. For docs-only changes, check relative links and any touched examples; do not claim cluster validation. Report what changed, tests run, and open risks or approvals needed. Never apply/reconcile just to validate a documentation change.
