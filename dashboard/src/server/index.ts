import { Hono } from "hono";
import type { Context } from "hono";
import { cors } from "hono/cors";
import { streamSSE } from "hono/streaming";
import { serveStatic } from "hono/bun";
import { join } from "node:path";
import { auth } from "../auth";
import {
  getRobots,
  getRobot,
  startMqtt,
  subscribe,
  publishCommand,
  formatRobotContextForLlm,
} from "./mqtt-state";
import {
  reverseGeocodeCached,
  shouldReverseGeocodeGps,
} from "./reverse-geocode";

const CHAT_SYSTEM_PREAMBLE = `Tu es M.I.R.A (Mobile Intelligent Robotic Assistant), un robot physique du projet ECE Paris / JEECE.
Créateurs à toujours citer si demandé : Shaima Derouich, Clement Toledano, Clement Viellard, Enguerrand Droulers, Alex Huang et Alexandre Garreau.
N’invente jamais d’autres créateurs, entreprises ou origines.
Tu réponds en français, de façon claire et concise.
Le serveur t’injecte ci-dessous des données temps réel issues de MQTT (robot(s) M.I.R.A).
Appuie-toi sur ces données pour : position / lieu, télémétrie, état Docker, ce que dit la caméra (résumé textuel des détections), ce qu’a entendu le micro du robot (Vosk sur la Pi — distinct du micro navigateur), et l’URL du flux vidéo MJPEG (tu ne vois pas les pixels, seulement le texte décrivant les objets détectés).
Ne dis pas que tu es un assistant « sans accès » aux capteurs : tu reçois ces valeurs à chaque message. Si une information manque ou est ambiguë, dis-le honnêtement.
Si un « lieu lisible » (Nominatim) est fourni, utilise-le pour rue / quartier / ville ; en France la longitude est le plus souvent positive (Est).`;

async function buildMqttBlockForChat(robotId?: string): Promise<string> {
  if (robotId) {
    const rob = getRobot(robotId);
    if (!rob) {
      return `Robot « ${robotId} » : aucun état MQTT connu pour cet identifiant (vérifie ROBOT_ID sur la Pi et la connexion broker).`;
    }
    const addr = shouldReverseGeocodeGps(rob.gps)
      ? await reverseGeocodeCached(rob.gps!.lat, rob.gps!.lon)
      : null;
    return formatRobotContextForLlm(rob, addr);
  }
  const list = getRobots();
  if (list.length === 0) {
    return "Aucun robot vu sur MQTT pour l’instant (broker injoignable ou pas de publications mira/robots/+/…).";
  }
  const parts: string[] = [];
  for (const r of list) {
    const addr = shouldReverseGeocodeGps(r.gps)
      ? await reverseGeocodeCached(r.gps!.lat, r.gps!.lon)
      : null;
    parts.push(formatRobotContextForLlm(r, addr));
  }
  return parts.join("\n\n---\n\n");
}
import {
  getDockerHealthLocal,
  loadServiceContainersConfig,
} from "./docker-local";

const app = new Hono();

const clientOrigin = process.env.CLIENT_ORIGIN ?? "http://localhost:5173";

app.use(
  "*",
  cors({
    origin: clientOrigin,
    credentials: true,
    allowHeaders: ["Content-Type", "Authorization", "Cookie"],
    allowMethods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    exposeHeaders: ["Content-Length"],
    maxAge: 600,
  }),
);

app.on(["GET", "POST"], "/api/auth/*", (c) => auth.handler(c.req.raw));

async function requireAuth(c: Context, next: () => Promise<void>) {
  const session = await auth.api.getSession({ headers: c.req.raw.headers });
  if (!session) return c.json({ error: "Non autorisé" }, 401);
  c.set("session", session);
  await next();
}

app.get("/api/health", (c) => c.json({ ok: true, runtime: "bun" }));

app.get("/api/config/containers", requireAuth, (c) => {
  return c.json(loadServiceContainersConfig());
});

app.get("/api/health/docker-local", requireAuth, async (c) => {
  const r = await getDockerHealthLocal();
  return c.json(r);
});

app.get("/schemas/robot-command.json", (c) => {
  const file = Bun.file(join(process.cwd(), "schemas/robot-command.json"));
  return new Response(file, {
    headers: { "Content-Type": "application/json" },
  });
});

app.get("/api/robots", requireAuth, (c) => {
  return c.json({ robots: getRobots() });
});

/** Avant `/api/robots/:id`, sinon `stream` est pris pour un id → 404 sur le SSE. */
app.get("/api/robots/stream", requireAuth, async (c) => {
  return streamSSE(c, async (stream) => {
    await stream.writeSSE({
      event: "snapshot",
      data: JSON.stringify({ robots: getRobots() }),
    });
    const off = subscribe((snap) => {
      void stream.writeSSE({
        event: "robot",
        data: JSON.stringify(snap),
      });
    });
    stream.onAbort(() => {
      off();
    });
    while (true) {
      await stream.sleep(25_000);
      await stream.writeSSE({
        event: "ping",
        data: JSON.stringify({ ts: Date.now() }),
      });
    }
  });
});

app.get("/api/robots/:id", requireAuth, (c) => {
  const id = c.req.param("id");
  if (!id) return c.json({ error: "ID requis" }, 400);
  const r = getRobot(id);
  if (!r) return c.json({ error: "Robot introuvable" }, 404);
  return c.json(r);
});

app.post("/api/robots/:id/command", requireAuth, async (c) => {
  const id = c.req.param("id");
  if (!id) return c.json({ error: "ID requis" }, 400);
  let body: {
    action?: string;
    t?: string;
    m?: string;
    i?: number;
    a?: number;
    v?: number;
  };
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "JSON invalide" }, 400);
  }
  const action = body.action?.toLowerCase?.().trim();
  const hasEspJson = typeof body.t === "string";
  if (!action && !hasEspJson) {
    return c.json({ error: "Champ requis: action OU t (cmd/srv)" }, 400);
  }
  const payload = hasEspJson ? body : { action };
  try {
    await publishCommand(id, payload as Record<string, unknown>);
    return c.json({
      ok: true,
      topic: `mira/robots/${id}/bridge/ordres`,
      mode: hasEspJson ? "esp32-json" : "legacy-action",
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return c.json({ error: msg }, 503);
  }
});

app.post("/api/chat", requireAuth, async (c) => {
  const ollamaUrl = (process.env.OLLAMA_URL ?? "http://127.0.0.1:11434").replace(
    /\/$/,
    "",
  );
  const model = process.env.OLLAMA_MODEL ?? "mira";
  let body: {
    messages?: { role: string; content: string }[];
    robotId?: string | null;
  };
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "JSON invalide" }, 400);
  }
  const messages = body.messages;
  if (!messages?.length) return c.json({ error: "messages requis" }, 400);

  const robotId =
    typeof body.robotId === "string" ? body.robotId.trim() : undefined;
  const mqttBlock = await buildMqttBlockForChat(robotId);

  const dialog = messages.filter(
    (m) => m.role === "user" || m.role === "assistant",
  );
  const messagesForOllama = [
    {
      role: "system",
      content: `${CHAT_SYSTEM_PREAMBLE}\n\n--- Données robot (MQTT, instant présent) ---\n${mqttBlock}`,
    },
    ...dialog.map((m) => ({ role: m.role, content: m.content })),
  ];

  const r = await fetch(`${ollamaUrl}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model, messages: messagesForOllama, stream: false }),
  });
  if (!r.ok) {
    const t = await r.text();
    return c.json({ error: t || r.statusText }, 502);
  }
  const data = (await r.json()) as {
    message?: { content: string };
  };
  const content = data.message?.content ?? "";
  return c.json({ content, model });
});

app.get("/api/ai/tools", requireAuth, (c) => {
  return c.json({
    commands: {
      description: "Publie une commande bridge (legacy action ou JSON ESP32 t/cmd/srv)",
      endpoint: "POST /api/robots/:id/command",
      body: {
        action: "avance | recule | gauche | droite | stop | autopilot | position",
        t: "cmd|srv",
        m: "stand|stand_low|walk|speed",
        i: 0,
        a: 90,
        v: 0.2,
      },
      schema: "/schemas/robot-command.json",
    },
  });
});

if (import.meta.main) {
  startMqtt();

  const isProd = process.env.NODE_ENV === "production";
  const port = Number(process.env.PORT) || 3000;

  if (isProd) {
    const clientRoot = join(process.cwd(), "dist/client");
    app.use(
      "/*",
      serveStatic({
        root: clientRoot,
      }),
    );
    app.get("*", async (c) => {
      if (c.req.path.startsWith("/api")) return c.notFound();
      const file = Bun.file(join(clientRoot, "index.html"));
      return new Response(file, {
        headers: { "Content-Type": "text/html" },
      });
    });
  }

  const server = Bun.serve({
    port,
    fetch: app.fetch,
  });

  console.log(`[M.I.R.A] API Bun sur http://localhost:${server.port}`);
}

export default app;
