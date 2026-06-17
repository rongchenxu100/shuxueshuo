import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FIXTURES_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../fixtures",
);

export async function loadFixture<T>(relativePath: string): Promise<T> {
  const filePath = path.join(FIXTURES_DIR, relativePath);
  const raw = await readFile(filePath, "utf8");
  return JSON.parse(raw) as T;
}
