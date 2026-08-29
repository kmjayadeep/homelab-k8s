import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { checksums, scanArtifact, UnsafeArtifactError, verifyChecksums, writeArtifact } from "../src/history.js";
import { defaultConfig } from "../src/config.js";

describe("safe history", () => {
  it.each([
    ["key.md", "-----BEGIN PRIVATE KEY-----\nsynthetic\n", "private-key"],
    ["fake-sealed.yaml", "safe", "forbidden-filename"],
    ["resource.yaml", "apiVersion: x\nkind: SealedSecret\n", "sealed-secret"],
    ["dump.md", "SERVICE_PASSWORD=synthetic-value\n", "environment-dump"],
  ])("blocks synthetic unsafe content without exposing it", (file, content, rule) => { try { scanArtifact(file, content); throw new Error("not blocked"); } catch (error) { expect(error).toBeInstanceOf(UnsafeArtifactError); expect((error as UnsafeArtifactError).rule).toBe(rule); expect((error as Error).message).not.toContain("synthetic-value"); } });
  it("bounds artifacts and creates stable checksums", async () => { const root = await mkdtemp(path.join(os.tmpdir(), "agent-history-")); await writeArtifact(root, "a.md", "hello\n", defaultConfig); const first = await checksums(root); expect(first).toBe(await checksums(root)); expect(first).toContain("a.md"); expect(await readFile(path.join(root, "a.md"), "utf8")).toBe("hello\n"); await import("node:fs/promises").then((fs) => fs.writeFile(path.join(root, "SHA256SUMS"), first)); await verifyChecksums(root); await writeArtifact(root, "b.md", "changed\n", defaultConfig); await expect(verifyChecksums(root)).rejects.toThrow("checksum"); });
});
