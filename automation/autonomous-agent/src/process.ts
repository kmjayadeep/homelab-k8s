import { spawn } from "node:child_process";

export interface CommandResult { command: string; code: number; stdout: string; stderr: string; timedOut: boolean; truncated: boolean }
export async function run(command: string, args: string[], options: { cwd: string; timeoutMs: number; input?: string; maxBytes?: number }): Promise<CommandResult> {
  const maxBytes = options.maxBytes ?? 64_000;
  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: options.cwd, shell: false, stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, GIT_TERMINAL_PROMPT: "0" } });
    const output: Buffer[] = []; const errors: Buffer[] = []; let bytes = 0; let truncated = false; let timedOut = false;
    const collect = (target: Buffer[]) => (chunk: Buffer) => { bytes += chunk.length; if (bytes <= maxBytes) target.push(chunk); else truncated = true; };
    child.stdout.on("data", collect(output)); child.stderr.on("data", collect(errors)); child.on("error", reject);
    const timer = setTimeout(() => { timedOut = true; child.kill("SIGTERM"); }, options.timeoutMs);
    child.on("close", (code) => { clearTimeout(timer); resolve({ command: [command, ...args].join(" "), code: code ?? 1, stdout: Buffer.concat(output).toString("utf8"), stderr: Buffer.concat(errors).toString("utf8"), timedOut, truncated }); });
    child.stdin.end(options.input);
  });
}
export function concise(result: CommandResult): string {
  const outcome = result.timedOut ? "TIMEOUT" : result.code === 0 ? "PASS" : "FAIL";
  return `- ${outcome}: \`${result.command}\`${result.truncated ? " (output truncated)" : ""}`;
}
