import path from "node:path";
import { mkdir } from "node:fs/promises";
import { run } from "./process.js";

async function git(repo: string, args: string[], input?: string) {
  const result = await run("git", args, { cwd: repo, timeoutMs: 60_000, ...(input === undefined ? {} : { input }) });
  if (result.code !== 0) throw new Error(`Git operation failed: git ${args[0]} (${result.stderr.trim().slice(0, 300)})`);
  return result.stdout.trim();
}
export async function repositoryRoot(cwd: string): Promise<string> { return path.resolve(await git(cwd, ["rev-parse", "--show-toplevel"])); }
export async function assertCleanBase(repo: string, base: string): Promise<void> {
  const branch = await git(repo, ["branch", "--show-current"]); if (branch !== base) throw new Error(`Source checkout must be on ${base}`);
  const status = await git(repo, ["status", "--porcelain", "--untracked-files=all"]); if (status) throw new Error("Source checkout has unrelated changes; commit or stash them first");
}
export async function createWorktree(repo: string, runId: string, prefix: string): Promise<{ branch: string; worktree: string }> {
  const branch = `${prefix}${runId}`; const worktree = path.resolve(repo, "..", ".agent-worktrees", runId); await mkdir(path.dirname(worktree), { recursive: true });
  const exists = await run("git", ["show-ref", "--verify", `refs/heads/${branch}`], { cwd: repo, timeoutMs: 10_000 });
  if (exists.code === 0) throw new Error(`Generated branch already exists: ${branch}`);
  await git(repo, ["worktree", "add", "-b", branch, worktree, "HEAD"]); return { branch, worktree };
}
export async function diff(worktree: string): Promise<string> { return await git(worktree, ["diff", "--no-ext-diff", "--no-textconv"]); }
export async function changedFiles(worktree: string): Promise<string[]> {
  const tracked = await git(worktree, ["diff", "--name-only", "--diff-filter=ACMR"]); const untracked = await git(worktree, ["ls-files", "--others", "--exclude-standard"]);
  return [...new Set(`${tracked}\n${untracked}`.split("\n").filter(Boolean))].sort();
}
export async function stageCommitPush(worktree: string, branch: string, paths: string[], message: string): Promise<string> {
  const current = await git(worktree, ["branch", "--show-current"]); if (current !== branch || branch === "main") throw new Error("Refusing to mutate an unexpected branch");
  if (paths.length) await git(worktree, ["add", "--", ...paths]); await git(worktree, ["diff", "--cached", "--check"]);
  const pending = await run("git", ["diff", "--cached", "--quiet"], { cwd: worktree, timeoutMs: 30_000 }); if (pending.code === 1) await git(worktree, ["commit", "-m", message]); else if (pending.code !== 0) throw new Error("Unable to inspect staged changes");
  await git(worktree, ["push", "--set-upstream", "origin", branch]); return await git(worktree, ["rev-parse", "HEAD"]);
}
export async function createPullRequest(worktree: string, branch: string, base: string, title: string, bodyFile: string): Promise<{ url: string; number: number }> {
  if (branch === base || base !== "main") throw new Error("Refusing unsafe pull-request target");
  const existing = await run("gh", ["pr", "view", branch, "--json", "url,number", "--jq", "[.url,.number]|@tsv"], { cwd: worktree, timeoutMs: 60_000 });
  let value: string;
  if (existing.code === 0) value = existing.stdout.trim(); else {
    const created = await run("gh", ["pr", "create", "--head", branch, "--base", base, "--title", title, "--body-file", bodyFile], { cwd: worktree, timeoutMs: 60_000 });
    if (created.code !== 0) throw new Error(`Pull-request creation failed: ${created.stderr.trim().slice(0, 300)}`); value = created.stdout.trim();
    const viewed = await run("gh", ["pr", "view", branch, "--json", "url,number", "--jq", "[.url,.number]|@tsv"], { cwd: worktree, timeoutMs: 60_000 });
    if (viewed.code !== 0) throw new Error("Pull request exists but metadata lookup failed"); value = viewed.stdout.trim();
  }
  const [url, number] = value.split("\t"); if (!url || !Number(number)) throw new Error("Invalid pull-request metadata"); return { url, number: Number(number) };
}
export { git };
