# Plan 0026: Music discovery agent on kagent

- Status: In progress (started 2026-11-07)
- Owner: Jayadeep KM
- Related: [plan 0020](0020-kagent-sre-agent.md), [plan 0022](0022-kagent-scheduled-tasks.md), [ADR 0002](../adrs/0002-autonomous-repository-agent.md)

## Goal and scope

A kagent agent, `music-curator`, that knows what is in the music library and what the operator likes, finds new music in the same vein, and posts a short weekly digest to Telegram with links to preview each suggestion. Feedback from the operator (like, dislike, want) is recorded so later digests improve and so a later download pipeline has a queue to work from.

In scope: discovery, the digest, and recording feedback.

Out of scope for this plan: downloading. That includes fixing Lidarr's download client, Soulseek or YouTube fetchers, tagging, and cleaning up the library. A follow-up plan consumes the "want" queue this plan produces. The agent never writes to Lidarr, Jellyfin or the NAS.

A plan is needed because this adds a new MCP server image, a Vault path, a stateful workload and a change to the Telegram bot.

## Starting state and prerequisites

Verified 2026-11-07:

- Library: about 385 tracks in 63 artist folders on TrueNAS `/mnt/main/media/tv/music` (31 GB, mostly FLAC, with `.lrc` lyrics). It is mostly Malayalam, Tamil and Hindi film music (A. R. Rahman, Ilaiyaraaja, Gopi Sunder, Shaan Rahman, Bijibal) plus some English pop. Folders were added by hand, and artist names are inconsistent ("A. R. Rahman", "A.R. Rahman", "A. R. Rahman & Javed Akhtar").
- Jellyfin 10.11.11 runs in Docker outside the cluster at `https://jellyfin.cosmos.cboxlab.com` and reads that share at `/tv/music`.
- Lidarr 3.1.6 (`torrents` namespace) has 3 artists and no import lists. Its download client points at the scaled-down `deluge-openvpn`. Lidarr is not used for discovery.
- kagent platform: `homelab-sre` and `homelab-gitops`, the LiteLLM `local-first` ModelConfig, the Telegram bot with `POST /task`, and CronJobs posting to it. `grafana-mcp` is the pattern for a Deployment plus `RemoteMCPServer`.

- Listening happens mainly on an Echo Mini portable player, filled by copying files out of Jellyfin (operator, 2026-11-07). Jellyfin play counts therefore do not reflect taste and are not used as a signal.

Unverified (checked in step 0):

- Whether the Echo Mini keeps a play history, favourites or playlist file that a sync could read (needs the player connected).
- How well Last.fm and YouTube Music cover Malayalam and Tamil film music, given that MusicBrainz coverage is known to be thin.
- Whether the local model handles about 12 narrow tools reliably.

Approvals needed: a new Jellyfin API key and a Last.fm API key imported into Vault by the operator.

## Taste signals

Jellyfin play counts are not used. In order of weight:

1. **Telegram feedback** (👍, 👎, ⬇) on earlier suggestions: explicit, and the main signal once a few digests have run.
2. **Library additions over time**: Jellyfin `DateCreated` per album. What the operator chose to add recently is the best implicit signal for a library that is curated by hand.
3. **Jellyfin favourites**, if the operator marks them while picking what to copy.
4. **The library as a whole**: languages, composers, eras and genres, as the baseline profile.
5. **Optional, later:** play data from the Echo Mini, if step 0 finds the player writes any.

## Design

```
CronJob (weekly) ──POST /task──▶ telegram-bot ──A2A──▶ music-curator (kagent Agent)
                                                         │ tools
                                                         ▼
                                                  music-mcp (Deployment + RemoteMCPServer)
                                                   ├─ Jellyfin API (library, recent additions, favourites)
                                                   ├─ Last.fm API (similar artists/tracks, tags)
                                                   ├─ YouTube Music (ytmusicapi, unauthenticated: related, search, charts)
                                                   └─ SQLite on a small Longhorn PVC (suggestions, feedback, want queue)
Telegram buttons 👍 / 👎 / ⬇ want ──▶ bot ──▶ music-mcp /feedback
```

Why a custom MCP server rather than giving the agent raw HTTP:

- A few narrow, deterministic tools work much better with the local model than generic fetch.
- The server normalises artist names: it splits "A & B" and "A, B" and folds "A. R." and "A.R." together.
- It deduplicates against the library and against earlier suggestions in code, not in the prompt.
- API keys stay in one pod.

State lives in the MCP server, not in kagent memory: suggestion history and feedback have to be exact and queryable.

### MCP tools (first cut)

| Tool | Source | Purpose |
| --- | --- | --- |
| `library_profile` | Jellyfin | Artists with track counts, top genres and years, normalised |
| `recent_additions(days)` / `favourites()` | Jellyfin | Recently added albums and favourited items (play counts deliberately not exposed) |
| `in_library(artist, title?)` | Jellyfin | Ownership check |
| `similar_artists(artist)` / `similar_tracks(artist, title)` | Last.fm | Neighbours with match score |
| `artist_top_tracks(artist)` | Last.fm, YT Music fallback | Entry points for a new artist |
| `related_tracks(artist, title)` | YT Music watch-playlist radio | Strongest signal for Indian film music |
| `new_releases(region)` / `search(query)` | YT Music | New film albums, resolving a suggestion to a preview link |
| `suggestion_history(days)` | SQLite | What was already suggested, with its feedback |
| `record_digest(items)` | SQLite | Stores this week's suggestions and returns their ids for the buttons |
| `feedback_summary()` | SQLite | Liked and disliked artists and tags, to steer the next run |

No tool writes to Lidarr, Jellyfin or the NAS.

### Agent

- `music-curator`, Declarative, `modelConfig: frontier` (DeepSeek), switched from `local-first` on 2026-11-07 for speed and accuracy.
- Workflow in the system message:
  1. Profile the library, recent additions and feedback.
  2. Pick 3–5 seeds, weighted towards liked feedback and recent additions.
  3. Expand each seed through Last.fm and YT Music.
  4. Drop anything owned, already suggested or disliked.
  5. Keep about 10 tracks and 3 albums, each with a one-line reason ("because you added *X*" or "because you liked *Y*").
  6. Call `record_digest`, then answer in the digest format.
- Mix rule: mostly the operator's core languages and genres, plus at most 2 "stretch" picks.
- A2A skills: `weekly-digest` and `ask` (for example "more like Sushin Shyam", "new Malayalam releases this month").

### Telegram

- A CronJob `kagent-music-digest` runs Friday 18:00 Europe/Zurich and posts `{agent: music-curator, title: "Music digest"}` to `/task`.
- Bot change: when the answer carries digest ids, add 👍, 👎 and ⬇ buttons per item that POST to `music-mcp` `/feedback`. The NetworkPolicy admits the bot to music-mcp.
- Bot change: a `/music <question>` command routes to `music-curator` instead of `homelab-sre`.

## Steps and gates

0. **Data check (no manifests).** Using a temporary key:
   - Query Jellyfin for `DateCreated` on music albums, to check that additions over time are visible.
   - With the Echo Mini connected, look for any history, favourites or playlist file on it.
   - Query Last.fm `artist.getSimilar` for 5 library artists (Gopi Sunder, Shaan Rahman, Bijibal, A. R. Rahman, Brodha V).
   - Query ytmusicapi `get_watch_playlist` for 5 library tracks from a cluster pod.

   Gate: at least one source gives relevant neighbours for the regional artists.
1. **Player sync, only if step 0 finds play data on the Echo Mini.** A small upload path (for example a `music-mcp` endpoint the operator hits after plugging the player in) imports it. Otherwise skip this step.
2. **`music-mcp` image** in `docker-images/music-mcp`: Python FastMCP, streamable HTTP, SQLite at `/data`. Gate: unit tests for name normalisation and deduplication, and a local `tools/list` and `library_profile` smoke test against Jellyfin.
3. **Vault** (prepared in homelab-iac, uncommitted). Keys go to `services/jellyfin/music-mcp` and `services/lastfm/music-mcp` (field `api_key`), added to `PATHS.md` and to the `kagent` External Secrets policy in `external-secrets.tf`. Import them with `import-jellyfin-music-mcp-key.sh` and `import-lastfm-music-mcp-key.sh` (stdin only). Gate: `terraform plan` shows only the kagent policy change; `vault kv metadata get` shows both paths.
4. **Manifests** in `clusters/titania/apps/kagent/`:
   - `music-mcp.yaml`: ExternalSecret, 1 Gi Longhorn PVC, Deployment with probes and limits, Service, NetworkPolicy (callers: kagent agent pods and the bot), `RemoteMCPServer`.
   - `agent-music-curator.yaml`.
   - Prompt and CronJob added to `scheduled-tasks.yaml`.
   - README section.

   Gate: `kustomize build | kubectl apply --dry-run=client` passes, then a PR. Restart the agent after the MCP server is serving (lesson from plan 0022).
5. **First digest by hand:** `kubectl -n kagent create job --from=cronjob/kagent-music-digest manual-music`. Gate: about 13 items, none already owned, each with a working YT Music link, and the operator judges at least half worth a listen.
6. **Bot buttons and `/music`** (bot image change in `docker-images/kagent-telegram-bot`). Gate: a button press shows up in `feedback_summary`, and the next digest excludes disliked artists.
7. Run for 3–4 weeks, tune the prompt and seed weights, then write the download follow-up plan around the ⬇ queue.

## Validation and rollback

- Each PR: kustomize build and client dry-run, plus the repository validation workflow.
- Rollback: revert the PR. Flux prunes the agent, the CronJob and the MCP server. The PVC holds only suggestion state, and deleting it needs operator approval. Revoke the Jellyfin and Last.fm keys.
- Risks:
  - **ytmusicapi** is an unofficial client. It can break or be rate-limited, and Last.fm remains the fallback source.
  - **Local model quality.** If tool use is unreliable, pin `frontier` for this agent.
  - **Jellyfin key scope.** Jellyfin keys are full admin keys. The MCP server calls only GET endpoints, and the key never reaches the model.

## Open decisions

Decided 2026-11-07: Jellyfin play counts are not a signal (listening happens on the Echo Mini); `frontier` model (changed from `local-first` after the first run); weekly digest of about 10 tracks and 3 albums; keys in Vault.

Still open:

- Whether ⬇ "want" should later feed Lidarr directly (albums with MusicBrainz ids), or a separate fetcher for film soundtracks that Lidarr cannot match.

## Outcome

Progress log:

- 2026-11-07, step 0 (partial): ytmusicapi `get_watch_playlist` from the operator's machine returns relevant neighbours for all 5 seeds (Shaan Rahman's *Aaro Nenjil* → Shaan Rahman, Justin Prabhakaran, Hesham Abdul Wahab, Sushin Shyam; *Kun Faya Kun* → Hindi Sufi and film tracks; Brodha V → Indian hip-hop). YouTube Music alone passes the gate. The global `get_explore` new releases are geolocated (Swiss results), so `new_releases` uses per-artist albums and singles instead. Last.fm and Jellyfin `DateCreated` are waiting on the keys. The cluster reaches Jellyfin (192.168.1.80) and music.youtube.com.
- 2026-11-07, step 2: `docker-images/music-mcp` written (MCP SDK 1.30 `FastMCP`, stateless streamable HTTP, Host allowlist). 12 unit tests pass. An end-to-end MCP smoke test against the real library list and live YouTube Music passed: 6 owned tracks dropped from one radio, duplicates rejected by `record_digest`, feedback stored, foreign Host header refused with 421. Library profile ranks album artists (composers) separately from credited singers, because singers dominate the raw credits.
- 2026-11-07, step 4: manifests written; kustomize build plus client and server dry runs pass. Image pinned to `ghcr.io/kmjayadeep/music-mcp:20261107080527` (first CI build, public pull verified).
- 2026-11-07, step 0 completed with the keys in Vault (Jellyfin `services/jellyfin/music-mcp` v1, Last.fm `services/lastfm/music-mcp` v2):
  - **Jellyfin:** 722 tracks, 136 albums, 397 artists (the August CSV export is stale). Albums were added as a bulk import in August 2026 (106), then 14 in September and 16 in October. The recent additions are late-1990s and 2000s Malayalam film albums (Vidyasagar, Mohan Sithara, Ouseppachan, Deepak Dev, Ilaiyaraaja), and the 2000s are the largest decade (261 tracks). The agent prompt now matches era as well as composer. User `jd` has no favourites yet.
  - **Last.fm:** `artist.getSimilar` gives strong Malayalam neighbours (Shaan Rahman → Deepak Dev, Gopi Sundar, Sushin Shyam, Jakes Bejoy; Bijibal → Shahabaz Aman, M. Jayachandran, Ouseppachan), but drifts into Telugu for Gopi Sunder. `track.getSimilar` returns nothing for regional tracks, so YouTube Music carries track-level discovery.
  - **Vault policy:** `terraform plan` shows only `vault_policy.external_secrets["kagent"]` gaining the two paths.
- 2026-11-07, step 5, first manual digest (`local-first`): the job ran 10 minutes and the bot timed out (`A2A_TIMEOUT_SECONDS` 600) before the answer arrived. 40 tool calls were made. `record_digest` was called five times, the last after the timeout. The digest stored three owned albums (no album ownership check) and some truncated album links. The picks themselves fit well: 1990s and 2000s Malayalam film songs and classic soundtracks seeded from the October additions. Fixes:
  - **Server:** new `digest_candidates` tool, which does the whole fan-out in one call (8.6 s live, 32 tracks, 8 albums, 33 owned dropped). `record_digest` now rejects owned albums, re-resolves links that are not valid YouTube Music URLs, and appends to the run's open digest (40 minutes).
  - **Agent:** a three-call workflow, and the `frontier` model at the operator's request.
  - **Bot:** `A2A_TIMEOUT_SECONDS` raised to 1200.
  The 29 suggestions from the failed run were never delivered.
- 2026-11-07, step 5, second manual digest (`frontier`, after PR #546), with the test store emptied (operator approved): 102 s end to end, 3 tool calls, one digest of 10 tracks and 3 albums, 2099 characters posted to Telegram. Every track had a working link and a seed reason. All three albums lacked links: candidate albums carried no URL, and the fallback search with the full credit list and "(Original Motion Picture Soundtrack)" matched nothing. Fixed in image `20261107083620` (album browse ids passed through from the radio; fallback search tries the short title with the first artist). Known data quirk: Jellyfin lists *Rasathanthram* (2006) as 2023, so its seed reason shows 2023.
- 2026-11-07: the operator judged the second digest "okay", so step 5 passes. Step 6: bot image `20261107090052` (docker-images `kagent-telegram-bot`) adds `/music <question>` (own A2A session per chat) and the digest buttons. After a `music-curator` answer the bot fetches `GET /digest` and posts one row per item only if the digest was created during that run. Presses call `POST /feedback` and tick the button in place. A local test with fake Telegram and music-mcp covered posting, pressing, label cells, foreign chats, `/music` routing and the old-digest skip.
- Risk to watch at step 5: the bot's `A2A_TIMEOUT_SECONDS` is 600, and a digest makes about 15 tool calls on the local model.
