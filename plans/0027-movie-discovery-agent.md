# Plan 0027: Movie discovery agent on kagent

- Status: In progress
- Owner: operator (jd)
- Related: [plan 0026](0026-music-discovery-agent.md) (music-curator, same pattern)

## Goal and scope

A weekly Telegram digest of about 8 movies the operator does not have yet. Each pick says why it was chosen, and the operator rates it with 👍 / 👎 / ⬇. The mix is Malayalam first, then English, with some Hindi.

In scope:

- a `movie-mcp` server
- a `movie-curator` kagent agent
- a Tuesday CronJob
- bot buttons and a `/movie` command

Out of scope for now:

- **Series and Sonarr.**
- **Streaming availability.** The operator watches only through Jellyfin, so the only thing that matters is whether a movie is in the library.
- **Acting on ⬇.** It fills a want list only. Sending it to Seerr or Radarr is a later step (step 7), once the picks are good.

## Starting state and prerequisites

Verified on 2026-11-07:

- **Jellyfin:** 105 movies and 31 series. 12 movies are marked played and none are favourites. Recent watches are ED: Extra Decent (2024), Bulbbul (2020), Avatar Aang (2026), Pradhama Drishtiya Kuttakkar (2026) and Thudakkam (2026). Top genres are Action, Thriller, Adventure, Drama and Comedy.
- **Radarr:** 67 movies; 41 have files and 24 are monitored but missing.
  - Languages: English 38, Malayalam 14, Hindi 9, Korean 3, others 3.
  - Download client: `deluge-wireguard`. There are 4 Prowlarr indexers; YourBittorrent has been failing for more than 6 hours. No import lists, and the queue is empty.
- **Seerr:** running at `seerr.cosmos.cboxlab.com`, but not used by this plan yet.
- **Approval** is needed for each Vault import and `terraform apply`, and for each PR merge.

Unlike music, watch history is a real signal here: the operator watches movies in Jellyfin.

## Taste signals

In order of weight:

1. Digest feedback: 👍 liked, ⬇ wanted, 👎 disliked.
2. Movies watched in Jellyfin, newest first (`Played` and `LastPlayedDate`).
3. Movies recently added to Radarr. This shows intent even when there is no file yet.
4. A library profile: original language, genres, decades and directors.

## Design

```
CronJob (Tue 19:00) ─POST /task─▶ telegram-bot ─A2A─▶ movie-curator (kagent Agent, frontier)
                                                        │ tools
                                                        ▼
                                                 movie-mcp (Deployment + RemoteMCPServer)
                                                  ├─ Jellyfin API (library, watched, GET only)
                                                  ├─ Radarr API (movies already added, GET only)
                                                  ├─ TMDB API v3 (recommendations, similar, discover by language, details)
                                                  └─ SQLite on a 1 Gi Longhorn PVC (digests, suggestions, feedback)
Telegram 👍 / 👎 / ⬇ ──▶ bot ──▶ movie-mcp /feedback      🔎 title button ──▶ TMDB page
```

Everything is keyed by TMDB id. Jellyfin (`ProviderIds.Tmdb`) and Radarr (`tmdbId`) both carry it, so the "owned" and "already added" checks are exact and need no fuzzy title matching.

It reuses plan 0026 code where it fits: the store layout, open-digest appending, the `/digest`, `/feedback` and `/wants` routes, and the bot button rows. It is a separate image, `docker-images/movie-mcp`, so each server stays small and can be rolled back alone.

### MCP tools (first cut)

| Tool | Source | Purpose |
| --- | --- | --- |
| `taste_profile()` | Jellyfin, Radarr | Recently watched, recently added, and language, genre, decade and director counts |
| `digest_candidates(seeds?)` | TMDB, Jellyfin, Radarr, SQLite | One-call fan-out, described below |
| `discover(language, since_days, kind)` | TMDB `discover/movie` | New or recent releases in a language, ordered by popularity with a vote floor |
| `similar(tmdb_id)` | TMDB recommendations and similar | Neighbours for one movie |
| `search(query, year?)` | TMDB | Resolve a title the operator mentions in `/movie` |
| `in_library(tmdb_id)` | Jellyfin, Radarr | Ownership and requested state |
| `feedback_summary()` / `suggestion_history()` | SQLite | Steering, and avoiding repeats |
| `record_digest(items)` | SQLite | Rejects owned, already added and already suggested movies; returns ids for the buttons |

`digest_candidates` works as follows:

- Seeds are the last 5 watched movies plus liked or wanted feedback. Each seed is expanded by its language (step 0 finding):
  - **English seeds:** TMDB recommendations.
  - **Malayalam and Hindi seeds:** TMDB recommendations return only English films, so these use `discover` in the seed's language with its first two genres, sorted by vote count, plus the filmography of the seed's director and two leading actors in that language.
- It adds `discover` results for Malayalam (last 120 days), English (last 60 days) and Hindi (last 90 days).
- It drops owned, already added, already suggested and disliked movies, and merges movies found from more than one seed.
- It returns candidates with their language, year, genres, rating, runtime and a short overview.

No tool writes to Jellyfin, Radarr or Seerr.

### Agent

- `movie-curator`: Declarative, `modelConfig: frontier`, with the same three-call workflow as music-curator (`feedback_summary` → `digest_candidates` → `record_digest`).
- Mix per digest: about 4 Malayalam, 3 English and 1 Hindi. Up to 1 "stretch" pick, for example Korean (seen in Radarr).
- Each pick gets a reason of at most 12 words naming the seed or the release ("new Malayalam thriller, Oct 2026").
- A2A skills: `weekly-digest` and `ask` ("something like Bulbbul", "new Malayalam releases this month").

### Telegram

- A CronJob `kagent-movie-digest` runs Tuesday 19:00 Europe/Zurich.
- The bot generalises the music digest buttons to a list of digest agents, each with its MCP URL. The 🔎 title button opens `themoviedb.org/movie/<id>`.
- `/movie <question>` routes to movie-curator in its own session.

## Steps and gates

0. **Data check.** With the TMDB key in Vault, from a pod:
   - TMDB recommendations for the 5 recent watches.
   - `discover` with `with_original_language=ml`, sorted by release date, for the last 120 days.
   - How many Jellyfin movies carry a TMDB id.

   Gate: relevant neighbours for at least 3 of 5 seeds, at least 5 Malayalam releases found, and more than 90 % of Jellyfin movies have TMDB ids.
1. **Vault.** In homelab-iac:
   - Import scripts for `services/tmdb/movie-mcp`, `services/jellyfin/movie-mcp` and `services/radarr/movie-mcp`, each with field `api_key`.
   - Add the three paths to the `kagent` External Secrets paths and to `PATHS.md`.

   Gate: `terraform plan` shows only the kagent policy change.
2. **`movie-mcp` image** in `docker-images/movie-mcp`, with unit tests for filtering and the store.
3. **Manifests** in `clusters/titania/apps/kagent/`:
   - `movie-mcp.yaml`: ExternalSecret, PVC, Deployment, Service, RemoteMCPServer and NetworkPolicy.
   - `agent-movie-curator.yaml`.
   - CronJob and prompt.
   - README.

   Allow egress to Radarr in `torrents`. That namespace has no NetworkPolicy today, so no change is expected; verify it.
4. **First digest by hand.** Gate: about 8 items, none owned or already in Radarr, and the language mix as above. The operator judges at least half worth watching.
5. **Bot:** buttons for movie digests and `/movie`. Gate: a press shows up in `feedback_summary`.
6. Run for 3–4 weeks and tune.
7. **Later plan:** ⬇ creates a Seerr request (or a Radarr add), and possibly a note on the 24 movies that are monitored but missing.

## Validation and rollback

- Each PR: kustomize build and client dry-run, plus the repository validation workflow.
- Rollback: revert the PR, and Flux prunes the objects. Deleting the PVC needs operator approval. Revoke the three keys.
- Risks:
  - **TMDB for Malayalam films:** the metadata is decent, but recommendations are thinner than for English. `discover` by language and the frontier model's own knowledge cover the gap. The step 0 gate checks this.
  - **Key scope:** Jellyfin and Radarr keys are full admin keys. The server calls GET endpoints only, and keys never reach the model.
  - **Only 12 movies are marked played,** so early seeds lean on Radarr additions and feedback.

## Open decisions

- Should ⬇ go through Seerr (keeps a request history) or straight to Radarr? Decided in step 7.

## Outcome

### Progress log

- **2026-11-07, step 1 (Vault):** homelab-iac #133 merged; the operator imported the TMDB, Jellyfin and Radarr keys. The operator ran `terraform apply` for the kagent policy the same day.
- **2026-11-07, step 0 (data check):**
  - **Jellyfin:** 102 of 105 movies carry a TMDB id. The 3 without one are badly named files (a French Harry Potter, Oru Jaathi Jathakam, a Star Wars release name) that need Identify in Jellyfin. Gate passed.
  - **TMDB recommendations:** 20 results for every seed, but **all English**, even for Malayalam and Hindi seeds. Thudakkam gave Beast and Interceptor; Bulbbul gave Hereditary. The gate failed for regional seeds.
  - **Fallback test:** same language and genres sorted by votes, plus filmographies. Gate passed, so the design above changed:
    - Bulbbul → Tumbbad, Stree, Qala (same director)
    - Pradhama Drishtiya Kuttakkar → Drishyam 1 and 2, Bramayugam, Kishkindha Kaandam, Charlie, Uyare
    - Thudakkam → Ohm Shanthi Oshaana, 2018, Rekhachithram, Lucifer
  - **`discover` in the last few months:** 63 Malayalam releases in 120 days, 109 Hindi in 90 days and 4601 English in 60 days. Malayalam votes are thin (0–10 per film), so for new releases the digest uses popularity, with a vote floor where votes exist. If that proves noisy, OMDb (IMDb ratings) is the next source.
- **2026-11-07, steps 2, 3 and 5 (image, manifests, bot):**
  - **Images:** docker-images `movie-mcp` (4 unit tests) built as `movie-mcp:20261107173638`. The bot now handles curator digests generically (`/movie`, `v:` callbacks; music keeps `f:`): `kagent-telegram-bot:20261107173552`.
  - **Local smoke test** against live Jellyfin, Radarr and TMDB: `digest_candidates` took 2 s and returned 35 KB. Malayalam seeds gave Drishyam, Manjummel Boys, Bramayugam, Aavesham and Ayyappanum Koshiyum.
  - **Logging issue it exposed:** httpx logged request URLs at INFO, including the TMDB key. music-mcp had been writing its Last.fm key to pod logs (and Loki) the same way. Both servers now keep `httpx` at WARNING (`music-mcp:20261107173625`). Rotating both keys is recommended.
- **2026-11-07, step 4 (first digest) and step 5 (bot), done:** homelab-k8s #558 merged.
  - **Rollout:** RemoteMCPServer discovery failed at first because it ran before the pod was ready. An annotation nudge and an agent restart fixed it, as in plan 0026; all 9 tools were discovered.
  - **Digests:** 6 manual digests of 8 movies each, 23–36 s per run, three tool calls, buttons posted, presses stored.
  - **Ratings** (26 of 48 rated):
    - **Malayalam:** 10 👍 and 1 👎. Older, well-known films do best (Drishyam 1 and 2, Manjummel Boys, Bangalore Days, Bramayugam, Jana Gana Mana, Kumbalangi Nights, Mukundan Unni Associates, Virus). New releases miss: Avaraachan & Sons 👎, and I'm Game unrated.
    - **English:** 9 👎 and 1 ⬇ (Heart of the Beast, a survival thriller).
    - **Hindi:** 2 👍 (Drishyam: The Conclusion, Kahaani), 2 👎, 1 ⬇ (Mom).
    - **Want list:** Mom, Heart of the Beast.
  - **Open-digest window:** it merged two quick manual reruns into the previous digest without buttons. Digests 2 and 4 were repaired by hand: the stray rows of digest 2 were deleted (operator approved), and digest 4's were moved to digest 5 with buttons re-posted through `/task`. `OPEN_DIGEST_MINUTES` is now 0 on both curators (#560, #561, #562).
  - **Key leak:** the TMDB key appeared in a local smoke-test transcript through httpx INFO logs. The servers keep `httpx` at WARNING. **Rotate the TMDB key** (still open).

### Next

- **Rotate the TMDB and Last.fm keys** and re-import them with the import scripts.
- **Prompt tuning (step 6):**
  - Mix: about 6 Malayalam (mostly well-known older films, at most 1 new release), 1 Hindi, and 1 English drawn from seeds rather than "new this month".
  - Reasons: say "because you liked" for feedback seeds and "because you watched" only for watch history, and never name the candidate as its own seed (digest 2 had "Bramayugam's seeds").
- **Step 7:** ⬇ to Seerr or Radarr. The want list is at `GET /wants`.
- **Jellyfin:** use Identify on the 3 movies without a TMDB id.
