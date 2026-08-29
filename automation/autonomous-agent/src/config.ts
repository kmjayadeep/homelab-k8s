import { readFile } from "node:fs/promises";
import path from "node:path";
import YAML from "yaml";
import type { Config, Reasoning, Role } from "./types.js";

export const defaultConfig: Config = {
  schemaVersion: 1,
  baseBranch: "main",
  branchPrefix: "agent/",
  localStateDirectory: ".agent-state",
  roles: {
    explorer: { model: "openai-codex/gpt-5.4-mini", reasoning: "medium" },
    planner: { model: "openai-codex/gpt-5.4", reasoning: "high" },
    planReviewer: { model: "openai-codex/gpt-5.6-sol", reasoning: "xhigh" },
    implementer: { model: "openai-codex/gpt-5.6-sol", reasoning: "high" },
    codeReviewer: { model: "openai-codex/gpt-5.6-terra", reasoning: "xhigh" },
    documentation: { model: "openai-codex/gpt-5.4", reasoning: "high" },
    governanceReviewer: { model: "openai-codex/gpt-5.6-sol", reasoning: "xhigh" },
  },
  limits: {
    planReviewIterations: 3, implementationReviewIterations: 4, governanceReviewIterations: 2,
    maxAgentTurnsPerStage: 20, stageTimeoutMinutes: 25, totalRuntimeMinutes: 120,
    maxArtifactBytes: 256_000, maxRunBytes: 5_000_000,
  },
  validation: { extraCommands: [] },
};
const roles: Role[] = ["explorer", "planner", "planReviewer", "implementer", "codeReviewer", "documentation", "governanceReviewer"];
const reasoning = new Set<Reasoning>(["off", "minimal", "low", "medium", "high", "xhigh", "max"]);
const keys = (value: object) => Object.keys(value);
function rejectUnknown(value: object, allowed: string[], where: string): void {
  const unknown = keys(value).filter((key) => !allowed.includes(key));
  if (unknown.length) throw new Error(`Unknown ${where} key: ${unknown.join(", ")}`);
}
function positive(value: unknown, name: string): asserts value is number {
  if (!Number.isSafeInteger(value) || Number(value) <= 0) throw new Error(`${name} must be a positive integer`);
}
export async function loadConfig(repo: string, file?: string): Promise<Config> {
  let raw: unknown = {};
  const configPath = file ? path.resolve(file) : path.join(repo, "automation/autonomous-agent/config.yaml");
  try { raw = YAML.parse(await readFile(configPath, "utf8")); }
  catch (error) {
    if (file || (error as NodeJS.ErrnoException).code !== "ENOENT") throw new Error(`Cannot load configuration: ${(error as Error).message}`);
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Configuration must be a YAML object");
  const input = raw as Record<string, unknown>;
  rejectUnknown(input, ["schemaVersion", "baseBranch", "branchPrefix", "localStateDirectory", "roles", "limits", "validation"], "configuration");
  if (input.schemaVersion !== undefined && input.schemaVersion !== 1) throw new Error("Unsupported configuration schemaVersion");
  const config = structuredClone(defaultConfig);
  if (typeof input.baseBranch === "string") config.baseBranch = input.baseBranch;
  if (typeof input.branchPrefix === "string") config.branchPrefix = input.branchPrefix;
  if (typeof input.localStateDirectory === "string") config.localStateDirectory = input.localStateDirectory;
  if (input.roles) {
    if (typeof input.roles !== "object" || Array.isArray(input.roles)) throw new Error("roles must be an object");
    rejectUnknown(input.roles, roles, "roles");
    for (const role of roles) {
      const value = (input.roles as Record<string, unknown>)[role];
      if (!value) continue;
      if (typeof value !== "object" || Array.isArray(value)) throw new Error(`roles.${role} must be an object`);
      rejectUnknown(value, ["model", "reasoning"], `roles.${role}`);
      const item = value as Record<string, unknown>;
      if (typeof item.model !== "string" || !item.model.startsWith("openai-codex/")) throw new Error(`roles.${role}.model must use openai-codex`);
      if (!reasoning.has(item.reasoning as Reasoning)) throw new Error(`Invalid reasoning for ${role}`);
      config.roles[role] = { model: item.model, reasoning: item.reasoning as Reasoning };
    }
  }
  if (input.limits) {
    if (typeof input.limits !== "object" || Array.isArray(input.limits)) throw new Error("limits must be an object");
    rejectUnknown(input.limits, keys(config.limits), "limits");
    for (const key of keys(input.limits)) {
      const value = (input.limits as Record<string, unknown>)[key]; positive(value, `limits.${key}`);
      (config.limits as unknown as Record<string, number>)[key] = value;
    }
  }
  if (input.validation) {
    if (typeof input.validation !== "object" || Array.isArray(input.validation)) throw new Error("validation must be an object");
    rejectUnknown(input.validation, ["extraCommands"], "validation");
    const commands = (input.validation as { extraCommands?: unknown }).extraCommands;
    if (!Array.isArray(commands)) throw new Error("validation.extraCommands must be an array");
    if (commands.length) throw new Error("Custom validation commands are not supported by the initial safety allowlist");
  }
  if (config.roles.implementer.model === config.roles.codeReviewer.model) throw new Error("Implementer and code reviewer must use different model IDs");
  if (config.baseBranch !== "main") throw new Error("The initial runner only supports main as baseBranch");
  if (path.isAbsolute(config.localStateDirectory) || config.localStateDirectory.includes("..")) throw new Error("localStateDirectory must be repository-relative");
  return config;
}
