import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { defaultConfig } from "../src/config.js";
import { acquireLock, assertTransition, createRun, legalTransitions, loadManifest, moveState, runDirectory } from "../src/state.js";

describe("durable state", () => {
  it("persists a run and legal transitions", async () => { const repo = await mkdtemp(path.join(os.tmpdir(), "agent-state-")); const manifest = await createRun(repo, defaultConfig, "safe requirement"); const directory = runDirectory(repo, defaultConfig, manifest.runId); await moveState(directory, manifest, "explore_and_plan"); expect((await loadManifest(directory)).state).toBe("explore_and_plan"); expect((await readFile(path.join(directory, "timeline.jsonl"), "utf8")).trim().split("\n")).toHaveLength(2); });
  it("accepts every declared transition and rejects representative illegal ones", () => { for (const [from, targets] of Object.entries(legalTransitions)) for (const to of targets) expect(() => assertTransition(from as keyof typeof legalTransitions, to)).not.toThrow(); expect(() => assertTransition("intake", "completed")).toThrow("Illegal"); expect(() => assertTransition("completed", "intake")).toThrow("Illegal"); });
  it("prevents concurrent mutation", async () => { const repo = await mkdtemp(path.join(os.tmpdir(), "agent-lock-")); const manifest = await createRun(repo, defaultConfig, "safe"); const directory = runDirectory(repo, defaultConfig, manifest.runId); const release = await acquireLock(directory); await expect(acquireLock(directory)).rejects.toThrow("locked"); await release(); expect(await acquireLock(directory)).toBeTypeOf("function"); });
});
