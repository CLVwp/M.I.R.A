/**
 * Lance l’API Bun (port 3000) et Vite (port 5173) — uniquement via Bun.
 */
import { resolve } from "node:path";

const root = resolve(import.meta.dir, "..");

const server = Bun.spawn({
  cmd: ["bun", "--hot", "src/server/index.ts"],
  cwd: root,
  stdout: "inherit",
  stderr: "inherit",
});

const vite = Bun.spawn({
  cmd: ["bun", "--bun", "vite"],
  cwd: root,
  stdout: "inherit",
  stderr: "inherit",
});

function shutdown(code: number) {
  server.kill();
  vite.kill();
  process.exit(code);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

server.exited.then((code) => {
  if (code !== 0) shutdown(code ?? 1);
});
vite.exited.then((code) => {
  if (code !== 0) shutdown(code ?? 1);
});
