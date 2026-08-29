import { readFile } from "node:fs/promises";
import path from "node:path";
import { changedFiles } from "./git.js";
import { concise, run, type CommandResult } from "./process.js";
import { scanArtifact } from "./history.js";

export interface ValidationReport { passed: boolean; summary: string; checks: Array<{ command: string; passed: boolean; timedOut: boolean; truncated: boolean }> }
async function hasCommand(command: string, cwd: string): Promise<boolean> { return (await run(command, ["--version"], { cwd, timeoutMs: 10_000, maxBytes: 1000 })).code === 0; }
export async function discoverKustomizations(worktree: string, files: string[]): Promise<string[]> {
  const found = new Set<string>();
  for (const relative of files.filter((file) => file.startsWith("clusters/titania/"))) {
    let directory = path.dirname(path.join(worktree, relative));
    while (directory.startsWith(path.join(worktree, "clusters", "titania"))) {
      try { await readFile(path.join(directory, "kustomization.yaml")); found.add(path.relative(worktree, directory)); break; } catch { directory = path.dirname(directory); }
    }
  }
  return [...found].sort();
}
export async function validate(worktree: string): Promise<ValidationReport> {
  const files = await changedFiles(worktree);
  for (const file of files) {
    if (/-decrypted\.ya?ml$|-sealed\.ya?ml$/i.test(file)) throw new Error(`Forbidden changed path: ${file}`);
    const target = path.join(worktree, file); const content = await readFile(target, "utf8").catch(() => ""); if (content) scanArtifact(file, content);
  }
  const results: CommandResult[] = [];
  results.push(await run("git", ["diff", "--check"], { cwd: worktree, timeoutMs: 60_000 }));
  const packageDirectory = path.join(worktree, "automation", "autonomous-agent"); const installed = await run("npm", ["ci", "--ignore-scripts", "--no-audit"], { cwd: packageDirectory, timeoutMs: 10 * 60_000 }); results.push(installed);
  if (installed.code === 0) results.push(await run("npm", ["run", "check", "--silent"], { cwd: packageDirectory, timeoutMs: 10 * 60_000 }));
  const roots = await discoverKustomizations(worktree, files);
  if (roots.length && (!(await hasCommand("kustomize", worktree)) || !(await hasCommand("kubectl", worktree)))) {
    results.push({ command: "kustomize + kubectl availability", code: 127, stdout: "", stderr: "", timedOut: false, truncated: false });
  } else for (const root of roots) {
    const built = await run("kustomize", ["build", root], { cwd: worktree, timeoutMs: 120_000, maxBytes: 5_000_000 }); results.push({ ...built, stdout: "", stderr: "" });
    if (built.code === 0 && !built.truncated) { const dryRun = await run("kubectl", ["apply", "--dry-run=client", "-f", "-"], { cwd: worktree, timeoutMs: 120_000, input: built.stdout }); results.push({ ...dryRun, stdout: "", stderr: "" }); }
  }
  const checks = results.map((result) => ({ command: result.command, passed: result.code === 0 && !result.timedOut && !result.truncated, timedOut: result.timedOut, truncated: result.truncated }));
  return { passed: checks.every((check) => check.passed), summary: results.map(concise).join("\n"), checks };
}
