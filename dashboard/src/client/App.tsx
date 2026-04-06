import { LoginPage } from "./pages/Login";
import { DashboardPage } from "./pages/Dashboard";
import { ServoControlPage } from "./pages/ServoControl";
import { authClient } from "./auth-client";
import { useState } from "react";

export function App() {
  const { data: session, isPending } = authClient.useSession();
  const [view, setView] = useState<"dashboard" | "servo">("dashboard");

  if (isPending) {
    return (
      <div className="app-shell">
        <p className="muted">Chargement…</p>
      </div>
    );
  }

  if (!session) {
    return <LoginPage />;
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <h1>M.I.R.A</h1>
        <p className="topbar-sub muted">Console — robots, carte, vidéo, assistant</p>
        <div className="topbar-nav">
          <button
            type="button"
            className={view === "dashboard" ? "btn-tab active" : "btn-tab"}
            onClick={() => setView("dashboard")}
          >
            Dashboard
          </button>
          <button
            type="button"
            className={view === "servo" ? "btn-tab active" : "btn-tab"}
            onClick={() => setView("servo")}
          >
            Controle servos
          </button>
        </div>
        <button
          type="button"
          className="btn-link"
          onClick={() => void authClient.signOut()}
        >
          Déconnexion
        </button>
      </header>
      <main className="main main--dashboard">
        {view === "dashboard" ? <DashboardPage /> : <ServoControlPage />}
      </main>
    </div>
  );
}
