import { mkdir, open, readFile, rename, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { randomBytes } from "node:crypto";
import YAML from "yaml";
import { states, type Config, type Manifest, type RunState, type TimelineEvent } from "./types.js";

export const legalTransitions: Record<RunState, RunState[]> = {
  intake: ["explore_and_plan", "failed"], explore_and_plan: ["plan_review", "failed"],
  plan_review: ["plan_revision", "implement", "failed"], plan_revision: ["plan_review", "failed"],
  implement: ["deterministic_validation", "failed"], deterministic_validation: ["code_review", "implementation_fix", "failed"],
  code_review: ["implementation_fix", "documentation_impact_and_update", "failed"], implementation_fix: ["deterministic_validation", "failed"],
  documentation_impact_and_update: ["governance_review", "failed"], governance_review: ["governance_fix", "final_validation", "failed"],
  governance_fix: ["deterministic_validation", "failed"], final_validation: ["awaiting_human_approval", "failed"],
  awaiting_human_approval: ["implementation_fix", "commit_and_push", "rejected", "failed"],
  commit_and_push: ["create_pull_request", "failed"], create_pull_request: ["record_pull_request_metadata", "failed"],
  record_pull_request_metadata: ["completed", "failed"], completed: [], failed: ["explore_and_plan", "plan_review", "implement", "deterministic_validation", "awaiting_human_approval", "commit_and_push", "create_pull_request", "record_pull_request_metadata"], rejected: [],
};
export function assertTransition(from: RunState, to: RunState): void {
  if (!legalTransitions[from].includes(to)) throw new Error(`Illegal state transition: ${from} -> ${to}`);
}
export function newRunId(now = new Date()): string {
  return `${now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")}-${randomBytes(4).toString("hex")}`;
}
export function runDirectory(repo: string, config: Config, runId: string): string { return path.join(repo, config.localStateDirectory, "runs", runId); }
async function atomicWrite(file: string, content: string): Promise<void> {
  const temporary = `${file}.tmp-${process.pid}-${randomBytes(3).toString("hex")}`;
  await writeFile(temporary, content, { mode: 0o600 }); await rename(temporary, file);
}
export async function createRun(repo: string, config: Config, requirements: string): Promise<Manifest> {
  const runId = newRunId(); const now = new Date(); const directory = runDirectory(repo, config, runId);
  await mkdir(path.join(directory, "history"), { recursive: true, mode: 0o700 });
  const manifest: Manifest = { schemaVersion: 1, runId, createdAt: now.toISOString(), updatedAt: now.toISOString(), state: "intake", baseBranch: config.baseBranch, iterations: { plan: 0, implementation: 0, governance: 0 }, usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, turns: 0 } };
  await atomicWrite(path.join(directory, "manifest.yaml"), YAML.stringify(manifest));
  await writeFile(path.join(directory, "requirements.md"), requirements, { mode: 0o600, flag: "wx" });
  await appendTimeline(directory, { schemaVersion: 1, timestamp: now.toISOString(), to: "intake", outcome: "started" });
  return manifest;
}
export async function loadManifest(directory: string): Promise<Manifest> {
  const value = YAML.parse(await readFile(path.join(directory, "manifest.yaml"), "utf8")) as Manifest;
  if (value.schemaVersion !== 1 || !states.includes(value.state)) throw new Error("Unsupported or invalid run manifest");
  return value;
}
export async function saveManifest(directory: string, manifest: Manifest): Promise<void> {
  manifest.updatedAt = new Date().toISOString(); await atomicWrite(path.join(directory, "manifest.yaml"), YAML.stringify(manifest));
}
export async function appendTimeline(directory: string, event: TimelineEvent): Promise<void> {
  const file = await open(path.join(directory, "timeline.jsonl"), "a", 0o600);
  try { await file.write(`${JSON.stringify(event)}\n`); await file.sync(); } finally { await file.close(); }
}
export async function moveState(directory: string, manifest: Manifest, to: RunState, outcome: TimelineEvent["outcome"] = "succeeded", artifact?: string): Promise<void> {
  assertTransition(manifest.state, to); const from = manifest.state; manifest.state = to;
  await saveManifest(directory, manifest); await appendTimeline(directory, { schemaVersion: 1, timestamp: new Date().toISOString(), from, to, outcome, ...(artifact === undefined ? {} : { artifact }) });
}
export async function acquireLock(directory: string): Promise<() => Promise<void>> {
  const lock = path.join(directory, ".lock");
  try { await mkdir(lock); } catch { throw new Error("Run is locked by another process"); }
  await writeFile(path.join(lock, "owner"), `${process.pid}\n`, { mode: 0o600 });
  return async () => { await unlink(path.join(lock, "owner")).catch(() => undefined); await import("node:fs/promises").then((fs) => fs.rmdir(lock)).catch(() => undefined); };
}
export async function findRun(repo: string, config: Config, runId: string): Promise<string> {
  if (!/^[A-Za-z0-9_-]+$/.test(runId)) throw new Error("Invalid run ID");
  const directory = runDirectory(repo, config, runId); await readFile(path.join(directory, "manifest.yaml")); return directory;
}
