# kagent skills

Skill directories loaded into kagent agents at pod start through `spec.skills.gitRefs` (public
repository, no credentials). Each directory has a `SKILL.md` with frontmatter (`name`, `description`)
and instructions, plus `scripts/`. Agents that carry a skill run the "full" Go ADK image, which adds the
built-in `bash`, `read_file`, `write_file` and `edit_file` tools; the skill text tells the model how
and when to use them.

| Skill | Used by | Purpose |
| --- | --- | --- |
| [gitops-coder](gitops-coder/SKILL.md) | `homelab-gitops` | Local workspace copy of homelab-k8s or homelab-iac, pinned `kustomize`/`kubeconform`, CI-equivalent validation and a diff before pushing through the GitHub MCP tools ([plan 0024](../../plans/0024-kagent-gitops-coding-agent.md)) |

Skills are read when the agent pod starts; after changing one, `kubectl -n kagent rollout restart deploy/<agent>`.
Script rule: no script removes anything it did not create itself (marker file `.gitops-coder-owned`, path must be inside `$WORKSPACE`).
