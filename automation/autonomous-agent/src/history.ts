import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Config } from "./types.js";

export class UnsafeArtifactError extends Error { constructor(public readonly rule: string, public readonly location: string) { super(`Artifact blocked by ${rule} at ${location}`); } }
const forbiddenNames = [/-decrypted\.ya?ml$/i, /-sealed\.ya?ml$/i, /\.env(?:\.|$)/i, /session.*\.jsonl$/i];
const rules: Array<[string, RegExp]> = [
  ["private-key", /-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----/m],
  ["credential-token", /\b(?:gh[opusr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b/m],
  ["environment-dump", /^(?:[ +]|-)?(?:[A-Z][A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|KEY)[A-Z0-9_]*)=\S+/m],
  ["sealed-secret", /^(?:[ +]|-)?kind:\s*SealedSecret\s*$/m],
  ["secret-resource-values", /^(?:[ +]|-)?kind:\s*Secret\s*$[\s\S]{0,2000}^(?:[ +]|-)?\s*(?:data|stringData):\s*$/m],
  ["raw-provider-payload", /"(?:reasoning_content|encrypted_content|system_fingerprint)"\s*:/m],
];
export function scanArtifact(relativePath: string, content: string): void {
  if (forbiddenNames.some((rule) => rule.test(path.basename(relativePath)))) throw new UnsafeArtifactError("forbidden-filename", `${relativePath}:filename`);
  if (content.includes("\0")) throw new UnsafeArtifactError("binary-content", `${relativePath}:1`);
  for (const [name, rule] of rules) {
    const match = rule.exec(content); if (!match) continue;
    const line = content.slice(0, match.index).split("\n").length;
    throw new UnsafeArtifactError(name, `${relativePath}:${line}`);
  }
}
async function totalSize(root: string): Promise<number> {
  let size = 0;
  async function walk(directory: string): Promise<void> {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name); if (entry.isDirectory()) await walk(file); else size += (await stat(file)).size;
    }
  }
  await walk(root); return size;
}
export async function writeArtifact(root: string, relativePath: string, content: string, config: Config): Promise<void> {
  if (path.isAbsolute(relativePath) || relativePath.split(path.sep).includes("..")) throw new Error("Artifact path escapes run history");
  const bytes = Buffer.byteLength(content); if (bytes > config.limits.maxArtifactBytes) throw new Error(`Artifact exceeds ${config.limits.maxArtifactBytes} bytes`);
  scanArtifact(relativePath, content);
  if ((await totalSize(root)) + bytes > config.limits.maxRunBytes) throw new Error(`Run history exceeds ${config.limits.maxRunBytes} bytes`);
  const target = path.join(root, relativePath); await mkdir(path.dirname(target), { recursive: true }); await writeFile(target, content, { mode: 0o600 });
}
export async function checksums(root: string): Promise<string> {
  const files: string[] = [];
  async function walk(directory: string): Promise<void> {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const file = path.join(directory, entry.name); if (entry.isDirectory()) await walk(file); else if (entry.name !== "SHA256SUMS") files.push(path.relative(root, file));
    }
  }
  await walk(root); files.sort(); const lines: string[] = [];
  for (const file of files) lines.push(`${createHash("sha256").update(await readFile(path.join(root, file))).digest("hex")}  ${file}`);
  return `${lines.join("\n")}\n`;
}
export async function verifyChecksums(root: string): Promise<void> {
  const expected = await readFile(path.join(root, "SHA256SUMS"), "utf8"); const actual = await checksums(root); if (expected !== actual) throw new Error("Run history checksum verification failed");
}
