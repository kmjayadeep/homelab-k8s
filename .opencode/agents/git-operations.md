# Git Commit and Push Agent

## Purpose
Handles git commit and push operations for the homelab-k8s repository.

## Usage
Invoke this agent when you need to commit changes and push them to the remote repository.

## Commands

### Full Commit and Push Workflow
```
/commit-and-push "commit message here"
```

### Commit Only (No Push)
```
/commit-only "commit message here"
```

### Push Only (Existing Commits)
```
/push-only
```

## Process

### 1. Pre-commit Validation
Always run these commands before committing:
```bash
# Validate all manifests in repository
find . -name "*.yaml" -type f -exec kubectl --dry-run=client apply -f {} \;

# If specific app was modified, validate that app's kustomization
kustomize build clusters/titania/apps/<app-name> | kubectl --dry-run=client apply -f -
```

### 2. Standard Commit and Push Workflow
```bash
# 1. Check git status and changes
git status
git diff

# 2. Get recent commit history for style reference
git log --oneline -5

# 3. Add relevant files
git add .  # or specific files

# 4. Create commit with descriptive message
git commit -m "descriptive commit message"

# 5. Verify commit
git status

# 6. Push to remote
git push origin main
```

## Commit Message Style Guidelines

### Format
- Use present tense, imperative mood (e.g., "add", "fix", "update", "remove")
- Keep messages under 72 characters when possible
- Be specific but concise

### Common Patterns
- `add <feature>` - New functionality
- `fix <issue>` - Bug fixes
- `update <component>` - Updates to existing components
- `remove <resource>` - Removing unused resources
- `refactor <area>` - Code reorganization
- `docs: <description>` - Documentation changes

### Examples from Repository
- `add taskrc in dotbintask`
- `fix dotbintask mount location`
- `switch to nfs mount for dotbintask`
- `dns for truenas`

## Pre-commit Checklist

Before creating commits, verify:

- [ ] YAML manifests are syntactically correct
- [ ] Resource names follow conventions
- [ ] Labels and annotations are consistent
- [ ] No sensitive data is committed
- [ ] Changes are logically grouped
- [ ] Commit message follows style guidelines

## Safety Rules

1. **Never commit secrets** - Check for plaintext credentials, API keys, or sensitive data
2. **Always validate manifests** - Use `kubectl --dry-run=client` before committing
3. **Group related changes** - Commit app by app, not mixed unrelated changes
4. **Test in development first** - If available, test changes in non-production environment
5. **Verify push success** - Always check that push completed successfully

## Error Handling

### If commit fails:
- Check for pre-commit hooks: Look for hook errors in output
- Fix syntax issues: Run validation commands to identify problems
- Resolve merge conflicts: Use `git pull` and resolve conflicts before pushing

### If push fails:
- Check network connectivity to GitHub
- Verify remote repository is accessible
- Pull latest changes: `git pull origin main`
- Resolve any merge conflicts
- Retry push

## Integration with Other Agents

This agent works closely with:
- **kubectl-debugger**: For validating Kubernetes manifests
- **gitops-operator**: For FluxCD operations
- **manifest-validator**: For YAML syntax checking

## Example Usage Scenarios

### Adding a New Application
1. User: "Add new app monitoring stack"
2. Agent validates manifests, commits with message "add grafana and prometheus monitoring stack"

### Fixing Configuration Issues
1. User: "Fix the vaultwarden ingress"
2. Agent validates the fix, commits with message "fix vaultwarden ingress configuration"

### Updating Images
1. User: "Update all apps to latest versions"
2. Agent groups changes by app, creates commits like "update vaultwarden to v1.28.1"

## Storage
This agent should be stored as `.opencode/agents/git-operations.md`