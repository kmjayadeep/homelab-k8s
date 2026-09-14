Goal: Update only README.md to add one concise sentence in the "Local repository agent" section stating that terminal runs show live progress, with no functional or behavioral changes.

Non-goals: No changes outside README.md; no manifest, automation, ADR, or validation-command changes; no cluster, Flux, Vault, or agent behavior changes.

Traceability:
- Prior finding: Add one short sentence to the Local repository agent section of README.md saying terminal runs show live progress.
- Operator feedback: Keep wording concise and change only README.md.

Files: README.md only.

Small steps:
1. Locate the "Local repository agent" section in README.md.
2. Add a single short sentence about terminal runs showing live progress.
3. Keep surrounding wording intact unless a minimal edit is needed for grammar/flow.
4. Review the diff to confirm README.md is the only changed file and the change is limited to that section.

Validation:
- Confirm the new sentence is present in the "Local repository agent" section.
- Confirm the wording is concise.
- Confirm only README.md changed.
- Since this is a documentation-only change, Kustomize/kubectl dry-run validation is not applicable.

Risks:
- Accidental edits outside the targeted section.
- Wording that is longer or broader than requested.

Documentation impact: README.md gains a brief clarification that terminal runs show live progress for the local repository agent.

Rollback: Revert the single README.md sentence addition (or the minimal README.md diff) if the wording needs to be withdrawn or revised.