import mqtt from "mqtt";
import type { MqttClient } from "mqtt";

export type RobotSnapshot = {
  id: string;
  meta: Record<string, unknown> | null;
  presence: { ts: number; online?: boolean } | null;
  telemetry: Record<string, unknown> | null;
  gps: {
    lat: number;
    lon: number;
    acc?: number;
    ts?: number;
    mock?: boolean;
    fix?: boolean;
    satellites?: number;
  } | null;
  /** Dernière transcription micro robot (Vosk → topic listening) */
  listening: { text: string; ts: number; source?: string } | null;
  /** Dernière phrase de détection caméra (IMX500 → vision/text ou legacy mira/vision/output) */
  vision: { text: string; ts: number; source?: string } | null;
  /** Rapport Docker publié par l’agent sur le robot (topic docker/status) */
  dockerStatus: {
    ts: number;
    services: Array<{ name: string; running: boolean; status?: string }>;
    error?: string;
  } | null;
  lastSeen: number;
};

type Listener = (snap: RobotSnapshot) => void;

const robots = new Map<string, RobotSnapshot>();
const listeners = new Set<Listener>();

let client: MqttClient | null = null;

function ensureRobot(id: string): RobotSnapshot {
  let r = robots.get(id);
  if (!r) {
    r = {
      id,
      meta: null,
      presence: null,
      telemetry: null,
      gps: null,
      listening: null,
      vision: null,
      dockerStatus: null,
      lastSeen: Date.now(),
    };
    robots.set(id, r);
  }
  return r;
}

function parseTopic(
  topic: string,
): { robotId: string; channel: string } | null {
  const m =
    /^mira\/robots\/([^/]+)\/(meta|presence|telemetry|gps|listening)$/.exec(
      topic,
    );
  if (!m) return null;
  return {
    robotId: m[1],
    channel: m[2] as "meta" | "presence" | "telemetry" | "gps" | "listening",
  };
}

export function getRobots(): RobotSnapshot[] {
  return [...robots.values()].sort((a, b) => b.lastSeen - a.lastSeen);
}

export function getRobot(id: string): RobotSnapshot | undefined {
  const r = robots.get(id);
  return r ? { ...r } : undefined;
}

/** Texte français pour le LLM (Ollama) : GPS, télémétrie, Docker, micro robot. */
export function formatRobotContextForLlm(
  r: RobotSnapshot,
  /** Libellé lieu (ex. Nominatim) — donné au modèle pour répondre « rue / ville ». */
  reverseAddress?: string | null,
): string {
  const lines: string[] = [];
  lines.push(`Identifiant : ${r.id}`);
  if (r.presence) {
    const on =
      r.presence.online === false
        ? "signalé hors ligne (LWT ou dernier message)"
        : "présence MQTT récente";
    lines.push(`Présence : ${on} (ts unix ${r.presence.ts}).`);
  } else {
    lines.push("Présence : aucune donnée MQTT.");
  }
  if (r.gps) {
    lines.push(
      `Position GPS (WGS84, degrés décimaux) : latitude ${r.gps.lat}° (nord si positif), longitude ${r.gps.lon}° (est si positif, ouest si négatif — en France métropolitaine c’est en général positif = Est).`,
    );
    if (reverseAddress?.trim()) {
      lines.push(
        `Lieu lisible (géocodage inverse OpenStreetMap / Nominatim, approximatif, pas une adresse postale certifiée) : ${reverseAddress.trim()}`,
      );
      lines.push(
        "Pour les questions du type « où est le robot ? », cite en priorité ce lieu (rue, quartier, ville) plutôt que seulement les décimales brutes.",
      );
    }
    if (r.gps.mock) {
      lines.push(
        "La position est simulée (MOCK_GPS côté robot), ce n’est pas le récepteur GNSS.",
      );
    } else {
      if (r.gps.fix === true) lines.push("Fix GNSS : oui.");
      else if (r.gps.fix === false) {
        lines.push(
          "Fix GNSS : non — les coordonnées peuvent être un repli (LAT/LON .env) en attendant le ciel.",
        );
      } else {
        lines.push(
          "Fix GNSS : non précisé — si la position ressemble à un point par défaut (ex. Paris), le port série GPS n’est peut‑être pas configuré.",
        );
      }
      if (r.gps.satellites != null) {
        lines.push(`Satellites utilisés (dernier GGA) : ${r.gps.satellites}.`);
      }
      if (r.gps.acc != null) {
        lines.push(`Précision indicative (champ acc) : ~${r.gps.acc} m.`);
      }
    }
  } else {
    lines.push("GPS : aucune donnée MQTT.");
  }
  if (r.meta && typeof r.meta.streamUrl === "string" && r.meta.streamUrl) {
    lines.push(`Flux vidéo temps réel (MJPEG, URL dans l’interface dashboard) : ${r.meta.streamUrl}`);
    lines.push(
      "Tu n’as pas accès aux images pixel par pixel dans cette conversation : seulement cette URL (pour l’utilisateur) et le résumé textuel des détections ci‑dessous.",
    );
  } else {
    lines.push(
      "Flux vidéo : aucune URL meta.streamUrl — la caméra peut tourner sans URL publiée vers le dashboard.",
    );
  }
  if (r.vision?.text) {
    const vts =
      typeof r.vision.ts === "number"
        ? new Date(r.vision.ts * 1000).toISOString()
        : String(r.vision.ts);
    lines.push(
      `Dernière analyse caméra (détection objets IMX500 / COCO, phrase en français) : « ${r.vision.text} » (ts unix ${r.vision.ts}, ~${vts} UTC).`,
    );
    lines.push(
      "Pour « que voit le robot ? », « qu’y a‑t‑il devant la caméra ? », s’appuyer sur cette phrase ; elle est périodique (cooldown côté vision), pas une image continue.",
    );
  } else {
    lines.push(
      "Vision caméra : aucune détection récente sur MQTT (topic mira/robots/<id>/vision/text ou legacy mira/vision/output).",
    );
  }
  if (r.listening?.text) {
    const lts =
      typeof r.listening.ts === "number"
        ? new Date(r.listening.ts * 1000).toISOString()
        : String(r.listening.ts);
    lines.push(
      `Entendu par le microphone du robot sur la Raspberry (STT Vosk, pas le navigateur) : « ${r.listening.text} » (ts unix ${r.listening.ts}, ~${lts} UTC).`,
    );
    lines.push(
      "Si l’utilisateur parle dans le navigateur du PC, ce n’est pas ce champ : ici c’est uniquement ce qu’a entendu le micro physique du robot.",
    );
  } else {
    lines.push(
      "Micro robot (Vosk) : aucune transcription sur MQTT — le service mira-stt doit tourner sur la Pi avec le même ROBOT_ID.",
    );
  }
  if (r.telemetry && Object.keys(r.telemetry).length > 0) {
    lines.push(`Télémétrie (JSON brut) : ${JSON.stringify(r.telemetry)}`);
  } else {
    lines.push("Télémétrie : aucune donnée.");
  }
  if (r.dockerStatus?.services?.length) {
    const svc = r.dockerStatus.services
      .map(
        (s) =>
          `${s.name} : ${s.running ? "actif" : "inactif"} (${s.status ?? "?"})`,
      )
      .join(" ; ");
    lines.push(`Conteneurs sur la Raspberry (rapport agent) : ${svc}.`);
  } else if (r.dockerStatus?.error) {
    lines.push(`Rapport Docker agent : erreur — ${r.dockerStatus.error}`);
  } else {
    lines.push("État Docker (agent) : pas encore de rapport reçu.");
  }
  if (r.meta && typeof r.meta.hostname === "string") {
    lines.push(`Hostname (meta) : ${r.meta.hostname}.`);
  }
  return lines.join("\n");
}

/** Résumé multi-robots si aucun id n’est ciblé (sans géocodage — préférer build côté chat). */
export function formatAllRobotsContextForLlm(): string {
  const list = getRobots();
  if (list.length === 0) {
    return "Aucun robot vu sur MQTT pour l’instant (broker injoignable ou pas de publications mira/robots/+/…).";
  }
  return list.map((r) => formatRobotContextForLlm(r)).join("\n\n---\n\n");
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function startMqtt(): void {
  const url = process.env.MQTT_URL ?? "mqtt://127.0.0.1:1883";
  if (client) return;

  client = mqtt.connect(url, {
    reconnectPeriod: 3000,
    connectTimeout: 10_000,
  });

  client.on("connect", () => {
    console.log(`[MQTT] Connecté ${url}`);
    client?.subscribe("mira/robots/+/meta", { qos: 0 });
    client?.subscribe("mira/robots/+/presence", { qos: 0 });
    client?.subscribe("mira/robots/+/telemetry", { qos: 0 });
    client?.subscribe("mira/robots/+/gps", { qos: 0 });
    client?.subscribe("mira/robots/+/listening", { qos: 0 });
    client?.subscribe("mira/robots/+/vision/text", { qos: 0 });
    client?.subscribe("mira/robots/+/docker/status", { qos: 0 });
    client?.subscribe("mira/vision/output", { qos: 0 });
    client?.subscribe("mira/bridge/feedback", { qos: 0 });
  });

  client.on("message", (topic, payload) => {
    const legacyBridgeRobot =
      process.env.MQTT_LEGACY_BRIDGE_ROBOT_ID?.trim() || "mira-robot";
    if (topic === "mira/bridge/feedback") {
      const r = ensureRobot(legacyBridgeRobot);
      r.lastSeen = Date.now();
      const raw = payload.toString("utf-8").trim();
      if (raw) {
        try {
          const data = JSON.parse(raw) as Record<string, unknown>;
          // Le firmware ESP32 publie typiquement {"t":"tel", ...}
          r.telemetry = data;
        } catch {
          r.telemetry = { raw };
        }
      }
      for (const l of listeners) l({ ...r });
      return;
    }

    const legacyVisionRobot =
      process.env.MQTT_LEGACY_VISION_ROBOT_ID?.trim() || "mira-robot";
    if (topic === "mira/vision/output") {
      const r = ensureRobot(legacyVisionRobot);
      r.lastSeen = Date.now();
      const raw = payload.toString("utf-8").trim();
      if (raw) {
        try {
          const data = JSON.parse(raw) as { text?: string; ts?: number; source?: string };
          if (typeof data.text === "string") {
            r.vision = {
              text: data.text,
              ts: typeof data.ts === "number" ? data.ts : Date.now() / 1000,
              source: data.source ?? "vision-json-legacy",
            };
          }
        } catch {
          r.vision = {
            text: raw,
            ts: Date.now() / 1000,
            source: "mira/vision/output",
          };
        }
      }
      for (const l of listeners) l({ ...r });
      return;
    }

    const visionM = /^mira\/robots\/([^/]+)\/vision\/text$/.exec(topic);
    if (visionM) {
      const r = ensureRobot(visionM[1]);
      r.lastSeen = Date.now();
      const raw = payload.toString("utf-8").trim();
      if (raw) {
        try {
          const data = JSON.parse(raw) as { text?: string; ts?: number; source?: string };
          if (typeof data.text === "string") {
            r.vision = {
              text: data.text,
              ts: typeof data.ts === "number" ? data.ts : Date.now() / 1000,
              source: data.source ?? "imx500",
            };
          }
        } catch {
          r.vision = {
            text: raw,
            ts: Date.now() / 1000,
            source: "vision-plain",
          };
        }
      }
      for (const l of listeners) l({ ...r });
      return;
    }

    const dockerM = /^mira\/robots\/([^/]+)\/docker\/status$/.exec(topic);
    if (dockerM) {
      const r = ensureRobot(dockerM[1]);
      r.lastSeen = Date.now();
      const text = payload.toString("utf-8");
      try {
        const data = JSON.parse(text) as {
          ts: number;
          services?: Array<{ name: string; running: boolean; status?: string }>;
          error?: string;
        };
        r.dockerStatus = {
          ts: data.ts,
          services: data.services ?? [],
          error: data.error,
        };
      } catch {
        /* ignore */
      }
      for (const l of listeners) l({ ...r });
      return;
    }

    const parsed = parseTopic(topic);
    if (!parsed) return;
    const r = ensureRobot(parsed.robotId);
    r.lastSeen = Date.now();
    const text = payload.toString("utf-8");
    try {
      const data = JSON.parse(text) as unknown;
      if (parsed.channel === "meta") r.meta = data as Record<string, unknown>;
      if (parsed.channel === "presence")
        r.presence = data as { ts: number; online?: boolean };
      if (parsed.channel === "telemetry")
        r.telemetry = data as Record<string, unknown>;
      if (parsed.channel === "gps") {
        const g = data as {
          lat: number;
          lon: number;
          acc?: number;
          ts?: number;
          mock?: boolean;
          fix?: boolean;
          satellites?: number;
        };
        r.gps = g;
      }
      if (parsed.channel === "listening") {
        const d = data as { text: string; ts: number; source?: string };
        if (typeof d.text === "string") r.listening = d;
      }
    } catch {
      // ignore invalid JSON
    }
    for (const l of listeners) l({ ...r });
  });

  client.on("error", (err) => {
    console.error("[MQTT]", err.message);
  });
}

export function publishCommand(
  robotId: string,
  payload: Record<string, unknown>,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!client?.connected) {
      reject(new Error("MQTT non connecté"));
      return;
    }
    const topic = `mira/robots/${robotId}/bridge/ordres`;
    const legacy = "mira/bridge/ordres";
    const body = JSON.stringify(payload);
    client.publish(topic, body, { qos: 0 }, (err1) => {
      if (err1) {
        reject(err1);
        return;
      }
      client?.publish(legacy, body, { qos: 0 }, (err2) => {
        if (err2) reject(err2);
        else resolve();
      });
    });
  });
}
