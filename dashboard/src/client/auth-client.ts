import { createAuthClient } from "better-auth/react";

/** Même origine en dev (proxy Vite) ; en prod le serveur Bun sert le front. */
export const authClient = createAuthClient({
  baseURL: typeof window !== "undefined" ? window.location.origin : "",
});
