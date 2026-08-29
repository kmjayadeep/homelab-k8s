import { mkdir, readFile, readdir, realpath, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { Type } from "typebox";
import { createAgentSession, DefaultResourceLoader, defineTool, getAgentDir, ModelRuntime, SessionManager, SettingsManager } from "@earendil-works/pi-coding-agent";
import type { AgentRequest, AgentResult, Config, Role, Usage } from "./types.js";
import { scanArtifact } from "./history.js";

export interface AgentAdapter { verify(config: Config): Promise<void>; run(request: AgentRequest, config: Config): Promise<AgentResult> }
const emptyUsage = (): Usage => ({ input: 0, output: 0, cacheRead: 0, cacheWrite: 0, turns: 0 });
function modelParts(value: string): [string, string] { const slash = value.indexOf("/"); return [value.slice(0, slash), value.slice(slash + 1)]; }
async function confined(root: string, requested: string, writing = false): Promise<string> {
  if (path.isAbsolute(requested)) throw new Error("Absolute paths are not permitted");
  const target = path.resolve(root, requested); const relative = path.relative(root, target);
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Path escapes repository");
  const check = writing ? path.dirname(target) : target; const resolved = await realpath(check);
  const rootReal = await realpath(root); if (resolved !== rootReal && !resolved.startsWith(`${rootReal}${path.sep}`)) throw new Error("Symlink escapes repository");
  return target;
}
async function confinedWrite(root: string, requested: string): Promise<string> {
  if (path.isAbsolute(requested)) throw new Error("Absolute paths are not permitted");
  const target = path.resolve(root, requested); const relative = path.relative(root, target);
  if (relative.startsWith("..") || path.isAbsolute(relative) || relative.split(path.sep).some((part) => [".git", ".agent-state"].includes(part))) throw new Error("Path is outside the writable repository boundary");
  let existing = path.dirname(target); while (true) { try { await realpath(existing); break; } catch { const parent = path.dirname(existing); if (parent === existing) throw new Error("No safe parent directory"); existing = parent; } }
  const rootReal = await realpath(root); const resolved = await realpath(existing); if (resolved !== rootReal && !resolved.startsWith(`${rootReal}${path.sep}`)) throw new Error("Symlink escapes repository");
  await mkdir(path.dirname(target), { recursive: true }); return target;
}
function tools(root: string, writable: boolean, submit: (value: unknown) => void) {
  const definitions = [
    defineTool({ name: "repo_read", label: "Read repository file", description: "Read a UTF-8 file inside the repository", parameters: Type.Object({ path: Type.String() }), execute: async (_id, value) => { if (value.path.split(/[\\/]/).some((part) => [".git", ".agent-state"].includes(part))) throw new Error("Protected path"); const text = (await readFile(await confined(root, value.path), "utf8")).slice(0, 100_000); scanArtifact(value.path, text); return { content: [{ type: "text", text }], details: {} }; } }),
    defineTool({ name: "repo_list", label: "List repository directory", description: "List entries inside a repository directory", parameters: Type.Object({ path: Type.String() }), execute: async (_id, value) => ({ content: [{ type: "text", text: (await readdir(await confined(root, value.path), { withFileTypes: true })).slice(0, 500).map((item) => `${item.isDirectory() ? "d" : "f"} ${item.name}`).join("\n") }], details: {} }) }),
    defineTool({ name: "repo_search", label: "Search repository", description: "Search text files by literal text", parameters: Type.Object({ query: Type.String(), path: Type.Optional(Type.String()) }), execute: async (_id, value) => {
      const start = await confined(root, value.path ?? "."); const matches: string[] = [];
      async function walk(target: string): Promise<void> { for (const item of await readdir(target, { withFileTypes: true })) { if ([".git", "node_modules", ".agent-state"].includes(item.name)) continue; const file = path.join(target, item.name); if (item.isDirectory()) await walk(file); else if ((await stat(file)).size < 1_000_000) { const text = await readFile(file, "utf8").catch(() => ""); text.split("\n").forEach((line, index) => { if (line.includes(value.query) && matches.length < 200) matches.push(`${path.relative(root, file)}:${index + 1}`); }); } } }
      await walk(start); return { content: [{ type: "text", text: matches.join("\n") || "No matches" }], details: {} };
    } }),
    defineTool({ name: "submit_result", label: "Submit structured result", description: "Submit the final JSON result for this stage", parameters: Type.Object({ result: Type.String({ description: "A JSON object encoded as a string" }) }), execute: async (_id, value) => { const parsed: unknown = JSON.parse(value.result); submit(parsed); return { content: [{ type: "text", text: "Result accepted. End the response." }], details: {} }; } }),
  ];
  if (writable) definitions.push(
    defineTool({ name: "repo_write", label: "Write repository file", description: "Write UTF-8 content inside the worktree", parameters: Type.Object({ path: Type.String(), content: Type.String() }), execute: async (_id, value) => { scanArtifact(value.path, value.content); const target = await confinedWrite(root, value.path); await writeFile(target, value.content, { encoding: "utf8", flag: "w" }); return { content: [{ type: "text", text: `Wrote ${value.path}` }], details: {} }; } }),
    defineTool({ name: "repo_edit", label: "Edit repository file", description: "Replace one unique exact string in a UTF-8 file", parameters: Type.Object({ path: Type.String(), oldText: Type.String(), newText: Type.String() }), execute: async (_id, value) => { if (value.path.split(/[\\/]/).some((part) => [".git", ".agent-state"].includes(part))) throw new Error("Protected path"); const target = await confined(root, value.path); const content = await readFile(target, "utf8"); const first = content.indexOf(value.oldText); if (first < 0 || content.indexOf(value.oldText, first + 1) >= 0) throw new Error("oldText must match exactly once"); const updated = content.replace(value.oldText, value.newText); scanArtifact(value.path, updated); await writeFile(target, updated); return { content: [{ type: "text", text: `Edited ${value.path}` }], details: {} }; } }),
  );
  return definitions;
}
export class PiAgentAdapter implements AgentAdapter {
  private runtime?: ModelRuntime;
  async verify(config: Config): Promise<void> {
    this.runtime = await ModelRuntime.create(); const available = await this.runtime.getAvailable();
    for (const role of Object.keys(config.roles) as Role[]) { const [provider, id] = modelParts(config.roles[role].model); if (!this.runtime.getModel(provider, id) || !available.some((model) => model.provider === provider && model.id === id)) throw new Error(`Configured model unavailable for ${role}: ${config.roles[role].model}`); }
  }
  async run(request: AgentRequest, config: Config): Promise<AgentResult> {
    if (!this.runtime) await this.verify(config); const role = config.roles[request.role]; const [provider, id] = modelParts(role.model); const model = this.runtime!.getModel(provider, id); if (!model) throw new Error(`Model not found: ${role.model}`);
    let structured: unknown; let text = ""; const usage = emptyUsage(); const settings = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: true, maxRetries: 2 } });
    const loader = new DefaultResourceLoader({ cwd: request.cwd, agentDir: getAgentDir(), settingsManager: settings, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, systemPromptOverride: () => request.system, appendSystemPromptOverride: () => [] }); await loader.reload();
    const customTools = tools(request.cwd, request.writable, (value) => { structured = value; });
    const { session } = await createAgentSession({ cwd: request.cwd, model, thinkingLevel: role.reasoning, modelRuntime: this.runtime!, customTools, tools: customTools.map((tool) => tool.name), resourceLoader: loader, sessionManager: SessionManager.inMemory(request.cwd), settingsManager: settings });
    let timedOut = false; let turnLimitReached = false;
    const unsubscribe = session.subscribe((event) => { if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") text += event.assistantMessageEvent.delta; if (event.type === "turn_start" && usage.turns >= request.maxTurns) { turnLimitReached = true; void session.abort(); } if (event.type === "turn_end") { usage.turns += 1; const raw = event.message as unknown as { usage?: Partial<Usage> }; if (raw.usage) { usage.input += raw.usage.input ?? 0; usage.output += raw.usage.output ?? 0; usage.cacheRead += raw.usage.cacheRead ?? 0; usage.cacheWrite += raw.usage.cacheWrite ?? 0; } } });
    const timeout = setTimeout(() => { timedOut = true; void session.abort(); }, request.timeoutMs);
    try { await session.prompt(`${request.prompt}\n\nYou must finish by calling submit_result exactly once. Do not include hidden reasoning in the result.`); }
    finally { clearTimeout(timeout); unsubscribe(); session.dispose(); }
    if (timedOut) throw new Error(`Agent ${request.role} timed out`); if (turnLimitReached) throw new Error(`Agent ${request.role} reached its turn limit`); if (structured === undefined) throw new Error(`Agent ${request.role} did not submit structured output`); return { text, structured, usage };
  }
}
export class FakeAgentAdapter implements AgentAdapter {
  constructor(private readonly responses: Partial<Record<Role, unknown[]>>) {}
  async verify(): Promise<void> {}
  async run(request: AgentRequest): Promise<AgentResult> { const queue = this.responses[request.role]; if (!queue?.length) throw new Error(`No fake response for ${request.role}`); return { text: "fake", structured: queue.shift(), usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, turns: 1 } }; }
}
