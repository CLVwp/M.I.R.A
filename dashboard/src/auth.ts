/**
 * Point d’entrée Better Auth (chemin attendu par `bun x auth@latest migrate --config src/auth.ts`).
 * SQLite via driver natif Bun uniquement.
 */
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { betterAuth } from "better-auth";
import { Database } from "bun:sqlite";

const dbPath = process.env.DATABASE_PATH ?? "./data/auth.sqlite";
mkdirSync(dirname(dbPath), { recursive: true });

export const auth = betterAuth({
  database: new Database(dbPath),
  secret:
    process.env.BETTER_AUTH_SECRET ??
    "dev-secret-change-me-for-production-min-32-chars-long!!",
  baseURL: process.env.BETTER_AUTH_URL ?? "http://localhost:3000",
  emailAndPassword: {
    enabled: true,
    requireEmailVerification: false,
  },
  trustedOrigins: [process.env.CLIENT_ORIGIN ?? "http://localhost:5173"],
});
