import { useEffect, useRef, useState } from "react";

type Msg = { role: "user" | "assistant"; content: string };

type ChatPageProps = {
  embedded?: boolean;
  /** Robot sélectionné sur le dashboard : contexte GPS/télémétrie injecté côté serveur. */
  robotId?: string | null;
};

/** API Web Speech du navigateur (Chrome / Edge) — distinct du conteneur Docker `mira-stt` (Vosk sur la Pi). */
type SpeechRec = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  abort: () => void;
  onresult: ((ev: {
    results: ArrayLike<{ 0: { transcript: string } }>;
  }) => void) | null;
  onerror: ((ev: { error: string; message?: string }) => void) | null;
  onend: (() => void) | null;
};

export function ChatPage({ embedded = false, robotId = null }: ChatPageProps) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(false);
  const [micHint, setMicHint] = useState<string | null>(null);
  const synth =
    typeof window !== "undefined" ? window.speechSynthesis : null;
  const recognitionRef = useRef<SpeechRec | null>(null);

  useEffect(() => {
    const w = window as unknown as {
      SpeechRecognition?: new () => SpeechRec;
      webkitSpeechRecognition?: new () => SpeechRec;
    };
    const SR = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!SR) {
      setMicHint(
        "Reconnaissance vocale indisponible (essayez Chrome ou Edge).",
      );
      return;
    }
    const r = new SR();
    r.lang = "fr-FR";
    r.continuous = false;
    r.interimResults = false;
    r.maxAlternatives = 1;
    r.onresult = (ev) => {
      const text = ev.results[0]?.[0]?.transcript ?? "";
      if (text) {
        setInput(text);
        setMicHint(null);
      }
    };
    r.onerror = (ev) => {
      const code = ev.error;
      if (code === "not-allowed" || code === "service-not-allowed") {
        setMicHint("Micro refusé : autorisez l’accès dans la barre d’adresse.");
      } else if (code === "no-speech") {
        setMicHint("Aucune voix détectée — réessayez.");
      } else if (code === "aborted") {
        /* ignore */
      } else {
        setMicHint(ev.message ?? `Erreur STT : ${code}`);
      }
    };
    r.onend = () => {
      setMicHint((prev) => (prev === "Écoute… parlez." ? null : prev));
    };
    recognitionRef.current = r;
  }, []);

  async function startMic() {
    setMicHint(null);
    const r = recognitionRef.current;
    if (!r) {
      setMicHint(
        "STT navigateur indisponible. Le conteneur Docker mira-stt (Vosk) est un autre pipeline, réservé au robot.",
      );
      return;
    }
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setMicHint(
        "Impossible d’accéder au micro (permission refusée ou pas de micro).",
      );
      return;
    }
    try {
      r.abort();
    } catch {
      /* */
    }
    try {
      setMicHint("Écoute… parlez.");
      r.start();
    } catch {
      setMicHint(
        "Impossible de démarrer la reconnaissance (réessayez dans quelques secondes).",
      );
    }
  }

  async function send() {
    const text = input.trim();
    if (!text) return;
    setInput("");
    const next: Msg[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setLoading(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          messages: next.map((m) => ({ role: m.role, content: m.content })),
          robotId: robotId || undefined,
        }),
      });
      const data = (await res.json()) as { content?: string; error?: string };
      if (!res.ok) {
        setMessages([
          ...next,
          { role: "assistant", content: data.error ?? "Erreur" },
        ]);
        return;
      }
      setMessages([
        ...next,
        { role: "assistant", content: data.content ?? "" },
      ]);
      if (synth && data.content) {
        const u = new SpeechSynthesisUtterance(data.content);
        u.lang = "fr-FR";
        synth.speak(u);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className={
        embedded ? "chat-page chat-page--embedded" : "chat-page"
      }
    >
      <header className="chat-head">
        <h2>Assistant M.I.R.A</h2>
        <p className="muted chat-stt-note">
          {embedded
            ? "STT = navigateur (Web Speech), pas mira-stt. Le serveur envoie au LLM le GPS / télémétrie MQTT du robot sélectionné à gauche."
            : "Texte + voix navigateur (Web Speech / synthèse). Le service Docker mira-stt (Vosk) est pour la Pi, pas ce panneau."}
        </p>
      </header>
      <div className="chat-log">
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            {m.content}
          </div>
        ))}
        {loading && <p className="muted">Réflexion…</p>}
      </div>
      <div className="chat-input-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void send()}
          placeholder="Message…"
        />
        <button type="button" onClick={() => void startMic()}>
          Micro
        </button>
        <button type="button" onClick={() => void send()} disabled={loading}>
          Envoyer
        </button>
      </div>
      {micHint && <p className="mic-hint">{micHint}</p>}
    </div>
  );
}
