import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { discoverKustomizations } from "../src/validation.js";

describe("Kustomization discovery", () => { it("finds the nearest changed Kustomization", async () => { const root = await mkdtemp(path.join(os.tmpdir(), "agent-kustomize-")); const app = path.join(root, "clusters/titania/apps/demo"); await mkdir(app, { recursive: true }); await writeFile(path.join(app, "kustomization.yaml"), "resources: []\n"); expect(await discoverKustomizations(root, ["clusters/titania/apps/demo/deployment.yaml"])).toEqual(["clusters/titania/apps/demo"]); }); });
