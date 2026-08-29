import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { defaultConfig, loadConfig } from "../src/config.js";

describe("configuration", () => {
  it("loads defaults when the default file is absent", async () => { const repo = await mkdtemp(path.join(os.tmpdir(), "agent-config-")); expect(await loadConfig(repo)).toEqual(defaultConfig); });
  it("rejects unknown keys", async () => { const repo = await mkdtemp(path.join(os.tmpdir(), "agent-config-")); const file = path.join(repo, "bad.yaml"); await writeFile(file, "schemaVersion: 1\nunsafe: true\n"); await expect(loadConfig(repo, file)).rejects.toThrow("Unknown configuration key"); });
  it("rejects identical implementation and review models", async () => { const repo = await mkdtemp(path.join(os.tmpdir(), "agent-config-")); const file = path.join(repo, "bad.yaml"); await writeFile(file, "roles:\n  implementer:\n    model: openai-codex/same\n    reasoning: high\n  codeReviewer:\n    model: openai-codex/same\n    reasoning: xhigh\n"); await expect(loadConfig(repo, file)).rejects.toThrow("different model IDs"); });
  it("rejects custom commands", async () => { const repo = await mkdtemp(path.join(os.tmpdir(), "agent-config-")); const file = path.join(repo, "bad.yaml"); await writeFile(file, "validation:\n  extraCommands:\n    - command: sh\n      args: []\n"); await expect(loadConfig(repo, file)).rejects.toThrow("not supported"); });
});
