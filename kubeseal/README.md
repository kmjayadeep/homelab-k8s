# kubeseal (legacy)

This directory contains historical Sealed Secrets public keys. All active
SealedSecrets were migrated to Vault and External Secrets; no SealedSecret
manifests remain in the repository or cluster.

Do not use these keys to create new SealedSecrets. A new bootstrap exception
requires explicit approval and an update to
`adrs/0001-vault-external-secrets.md`. The keys remain only until the retained
Sealed Secrets controller is removed in a separate change.
