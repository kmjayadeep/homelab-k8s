# Plan 0031: Home Assistant and kagent

- Status: Completed 2026-11-15 (started 2026-11-14)
- Owner: Jayadeep KM
- Related: [plan 0020](0020-kagent-sre-agent.md), [plan 0022](0022-kagent-scheduled-tasks.md), [plan 0028](0028-finance-curator.md)

## Goal and scope

Connect Home Assistant (HAOS VM on `jupiter`, `home-assistant.cosmos.cboxlab.com`) to the cluster in three ways:

1. `/home` in Telegram: a `home` agent that reads the house and controls the living room light, the Echo Dot, the weekday wake time and to-do lists through Home Assistant's MCP server.
2. Socket power in Prometheus: scrape Home Assistant's `/api/prometheus` so the Hombli sockets that power the servers can be queried by `homelab-sre` through the Grafana MCP tools.
3. A homelab line in the 08:00 Echo Dot briefing: `homelab-sre` writes `OK` or one spoken sentence to a Home Assistant text helper at 07:45 on weekdays.

Out of scope: any agent control of the homelab sockets, presence-based automations (those live in Home Assistant), and keeping Home Assistant's own configuration in Git.

## Starting state and prerequisites

Done in Home Assistant on 2026-11-14, outside Git:

- Non-admin, local-only user `kagent` (password in the operator's `pass`). Two long-lived tokens written straight to Vault, never displayed: `services/home-assistant/kagent` (MCP and the briefing CronJob) and `services/home-assistant/prometheus` (scrape).
- Model Context Protocol Server integration, Assist API only. The broader "Home Assistant" tool set, which can perform any action, is not enabled.
- Assist exposure tightened: the four homelab socket switches, the AdGuard switches and other people's or stale media players are unexposed, and new entities are no longer exposed automatically. Exposed: the bulb, the Echo Dot, `input_datetime.wake_time`, `script.set_wake_time`, socket power and daily energy sensors, weather, sun, person, to-do lists.
- `prometheus:` added to `configuration.yaml` (namespace `hass`, filtered to the socket sensors and switches, the bulb and Fast.com); a backup is at `configuration.yaml.bak-20261114`. `/api/prometheus` returns 200 for the `kagent` user.
- Helper `input_text.briefing_homelab_note`; the `morning_briefing` automation reads it.
- SSH add-on reachable on port 22222 with the operator's keys, for future YAML edits.

Required before merging this repository's change: the Vault policy change in `homelab-iac` (`vault-config/external-secrets.tf`: `services/home-assistant/kagent` for the `kagent` role, new role `monitoring-home-assistant`) is applied. Prometheus mounts `home-assistant-prometheus` and will not start without it.

The `/home` command needs a `kagent-telegram-bot` image with `HOME_AGENT` support (`docker-images`); until then the env var is ignored.

## Design

- The `home` agent uses `sensitive` (local only): tool results include presence and household state.
- The HA token is the only credential, and it belongs to a non-admin user. Home Assistant tokens cannot be scoped, so the token itself can call any service. It reaches only the kagent MCP connection (as a header from a Secret) and the CronJob, never the model. What the model can do is bounded by the Assist API and the exposed entity list, not by the token.
- The socket switches stay unexposed. The prompt also forbids switching them, but exposure is the control that matters.
- The briefing CronJob clears and then sets the helper so an unchanged sentence still counts as written that day. Any failure leaves the helper alone, and the briefing skips the line because it was not changed today.

## Steps and gates

1. Apply the `homelab-iac` Vault change. Gate: `vault policy read` shows both paths.
2. Merge this change. Gate: ExternalSecrets `home-assistant-kagent` and `home-assistant-prometheus` Ready; `RemoteMCPServer/home-assistant` accepted with the listed tools; Prometheus pod ready and target `home-assistant` up; `hass_sensor_power_w` returns four series.
3. Deploy the bot image with `/home`. Gate: "/home is the light on" and "/home set the wake time to 07:00" answer correctly; "/home turn off pluto" is refused and no switch changes.
4. Run `kubectl -n kagent create job --from=cronjob/home-briefing-note manual-note`. Gate: the job logs `note: ...` and the helper holds the same text.

## Validation and rollback

`kustomize build` and client dry-run for `clusters/titania/apps/kagent` and `clusters/titania/infra/monitoring`. To roll back, revert the PR; in Home Assistant, delete the MCP Server integration and the `kagent` user, which revokes both tokens.

## Outcome

Completed 2026-11-15. All four gates passed:

1. Vault: `homelab-iac#158` applied (2 added, 1 changed); the `kagent` policy reads `services/home-assistant/kagent` and the new `monitoring-home-assistant` role reads `services/home-assistant/prometheus`.
2. #617 merged: both ExternalSecrets Ready, `RemoteMCPServer/home-assistant` accepted, Prometheus target `home-assistant` up, and `hass_sensor_power_w` returns the four socket series.
3. `docker-images#23` (`/home`, JWT redaction) built as `kagent-telegram-bot:20261114212110` and deployed by #618. In Telegram, the agent reported the light's state, set the wake time, and refused to switch a homelab socket.
4. A manual `home-briefing-note` job wrote `OK` to `input_text.briefing_homelab_note`.

Changed in Home Assistant during the same work, outside Git:

- Sockets renamed `jupiter`, `orion` (about 90 W; was `pluto_socket_*`), `mars` and `pluto` (was `hombli_smart_socket_4_*`), with a new Pluto daily meter. The Prometheus series changed labels with the rename, so history before 2026-11-15 sits under the old names.
- Presence comes from an Nmap Tracker scan of the phone on Wi-Fi (`device_tracker.jd_s24_wifi`, phone set to use its device MAC), because the Companion app trackers stopped reporting location on 2026-10-28.
