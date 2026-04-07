import { useState } from "react";
import { authClient } from "../auth-client";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("Opérateur");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === "signup") {
        const { error: err } = await authClient.signUp.email({
          email,
          password,
          name,
        });
        if (err) setError(err.message ?? "Inscription impossible");
      } else {
        const { error: err } = await authClient.signIn.email({
          email,
          password,
        });
        if (err) setError(err.message ?? "Connexion impossible");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <h1>M.I.R.A</h1>
        <p className="muted">Console de gestion — connexion</p>
        <div className="tabs">
          <button
            type="button"
            className={mode === "signin" ? "tab active" : "tab"}
            onClick={() => setMode("signin")}
          >
            Connexion
          </button>
          <button
            type="button"
            className={mode === "signup" ? "tab active" : "tab"}
            onClick={() => setMode("signup")}
          >
            Inscription
          </button>
        </div>
        <form onSubmit={(e) => void onSubmit(e)}>
          {mode === "signup" && (
            <label>
              Nom affiché
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </label>
          )}
          <label>
            E-mail
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </label>
          <label>
            Mot de passe
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete={
                mode === "signup" ? "new-password" : "current-password"
              }
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={loading}>
            {loading ? "…" : mode === "signin" ? "Se connecter" : "Créer un compte"}
          </button>
        </form>
      </div>
    </div>
  );
}
