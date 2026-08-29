# Autonomous agent run records

This tree contains bounded audit records created by the local runner. A record is committed on the generated branch together with its implementation and reaches `main` only through human PR merge.

Records use `YYYY/MM/<run-id>/` and contain a versioned manifest, requirements, append-only timeline, exploration, every plan and verdict, bounded text patch snapshots, validation summaries, documentation impact, governance verdicts, human approval, final summary, PR metadata, and `SHA256SUMS`. Binary changes are named and hashed rather than embedded. Operational state remains in ignored `.agent-state/`.

Never add raw Pi session JSONL, prompts containing sensitive data, hidden reasoning, provider request/response payloads, environment dumps, unbounded logs, credentials, private keys, Kubernetes Secret or Vault values, `*-decrypted.yaml`, `*-sealed.yaml`, or `SealedSecret` resources. A suspected secret blocks publication and is reported only by path, rule, and location—not by value.

Checksums cover all record files except `SHA256SUMS` itself. `pr.yaml` is added in a second metadata commit after PR creation. Records are audit evidence, not authority to weaken `AGENTS.md` or repository safety policy.
