---
name: gitops-coder
description: Local workspace for editing and validating kmjayadeep/homelab-k8s and kmjayadeep/homelab-iac before pushing through the GitHub MCP tools. Provides setup, validate and changed scripts.
---
# gitops-coder

Use this skill for every request that changes files in homelab-k8s or homelab-iac. It gives you a
local copy of the repository under `$WORKSPACE/<repo>` (default `/workspace/<repo>`) so you can read
and edit files precisely with `read_file` and `edit_file`, validate the result with the same tools the
CI workflow runs, and see exactly what you changed before you push. Pushing, branching and pull
requests stay on the GitHub MCP tools (`create_branch`, `push_files`, `create_pull_request`): this pod
holds no GitHub credentials and must not try to obtain any.

## Scripts

All scripts live in `/skills/gitops-coder/scripts/` and are run with `bash`.

- `setup.sh <repo> [ref]` (repo is `homelab-k8s` or `homelab-iac`; ref defaults to `main`):
  downloads pinned, checksum-verified `kustomize` and `kubeconform` into `$WORKSPACE/bin`
  (once), fetches the repository tarball at `ref` into `$WORKSPACE/<repo>` and keeps a pristine copy in
  `$WORKSPACE/.orig/<repo>`. Prints the commit SHA it fetched. Run it at the start of every request; an
  existing checkout is replaced so you always start from the current `main`.
- `validate.sh <repo> [path ...]`: for homelab-k8s, runs `kustomize build` and `kubeconform` (strict,
  core and CRD schemas, like `.github/workflows/validate.yaml`) on each given directory, or on every
  directory under `clusters/` that holds a `kustomization.yaml` when no path is given. There is no
  `kubectl` here: a client dry-run cannot check custom resources without a cluster, and kubeconform
  with the CRD catalog is what CI runs. Directories whose kustomization pulls a
  remote git base (for example `infra/metallb`) are skipped with a note, because the image has no git;
  CI validates them after you push. For homelab-iac there is no local
  validator: the script only checks Python files compile and reminds you that CI runs `terraform fmt`.
  Exit code 0 means everything passed.
- `changed.sh <repo>`: lists added, modified and deleted files relative to the pristine copy and prints
  the unified diff. Use it before pushing to confirm the change is exactly what was asked, and use its
  file list to decide which files to send to `push_files`.

## Workflow

1. `bash /skills/gitops-coder/scripts/setup.sh <repo>`.
2. Read the files you need with `read_file` from `$WORKSPACE/<repo>/...` (AGENTS.md, the workflow docs,
   the files you will change). Use `bash` with `find`, `grep` or `rg` to locate things.
3. Edit with `edit_file` (exact string replacement) or `write_file` for a new file. Keep the change
   minimal.
4. `bash /skills/gitops-coder/scripts/validate.sh <repo> <dir of each changed kustomization>`; fix and
   re-run until it passes.
5. `bash /skills/gitops-coder/scripts/changed.sh <repo>` and check the diff.
6. For each changed file, `read_file` its full content from the workspace and send it unchanged in one
   `push_files` call on your `kagent/*` branch; then open the pull request. Mention in the PR body that
   the change was validated locally with kustomize and kubeconform.

## Limits

- `bash` runs inside your own pod. It has no kubeconfig and no GitHub token; do not look for or try to
  create either. Do not install software, do not reach the cluster, do not run anything the scripts do
  not already do apart from `find`, `grep`, `rg`, `diff`, `cat`, `ls` and the validators. Never run
  `rm -rf`; the scripts remove only directories they created themselves.
- The workspace is ephemeral: it disappears when the pod restarts. Anything not pushed is lost.
- Never edit files under `$WORKSPACE/.orig/`.
