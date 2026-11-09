# Plan 0028: Finance curator on kagent

- Status: In progress (started 2026-11-09)
- Owner: Jayadeep KM
- Related: [plan 0026](0026-music-discovery-agent.md), [plan 0027](0027-movie-discovery-agent.md)

## Goal and scope

Answer money questions over Telegram (`/money`) from the operator's private Beancount ledger, without the data leaving the cluster's model backend.

This repository is public, so this plan holds only the cluster side. Banks, payees, amounts and the import pipeline are tracked in the private ledger repository.

In scope: read-only tools, the agent, and the bot command. Out of scope here: importing data, writing to the ledger, and any action on an account.

## Starting state and prerequisites

- Fava reads a Git checkout of the ledger through the `ledger-sync` sidecar (#571).
- The `sensitive` LiteLLM alias is local only. `frontier` and `local-first` can reach an outside provider.
- A local-model curator made 40 tool calls and hit the bot's 600-second timeout in plan 0026, so tools must do the work.

## Design

`finance-mcp` runs as a container in the Fava pod and reads the same read-only checkout. `finance-curator` uses only `sensitive`. Figures are computed in code, and the model picks a tool and reports the result. A NetworkPolicy limits port 8000 to that agent and the kagent controller.

Accepted exposure: agent session history in kagent's Postgres, and answers on Telegram. The tool server logs no arguments or results.

## Steps and gates

1. Deploy. Gate: pod ready, `RemoteMCPServer` accepted with five tools, Fava still serving.
2. Ask `/money` for net worth, a tag total and a period. Gate: answers match the tools, at most three tool calls, well inside the 600-second timeout.
3. Confirm no ledger rows in `finance-mcp` logs or Loki.

## Validation and rollback

Run the Kustomize builds and client dry-runs. To roll back, revert the PR: the agent and server are stateless.

## Outcome

To be recorded on completion.
