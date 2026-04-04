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
      dockerStatus: null,
      lastSeen: Date.now(),
    };
    robots.set(id, r);
  }
  return r;
}

function parseTopic(topic: string): { robotId: string; channel: string } | null {
  const m =
    /^mira\/robots\/([^/]+)\/(meta|presence|telemetry|gps|listening)$/.exec(
      topic,
    );
  if (!m) return null;
  return {
    robotId: m[1],
    channel: m[2] as
      | "meta"
      | "presence"
      | "telemetry"
      | "gps"
      | "listening",
  };
}

export function getRobots(): RobotSnapshot[] {
  return [...robots.values()].sort((a, b) => b.lastSeen - a.lastSeen);
}

export function getRobot(id: string): RobotSnapshot | undefined {
  const r = robots.get(id);
  return r ? { ...r } : undefined;
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
    client?.subscribe("mira/robots/+/docker/status", { qos: 0 });
  });

  client.on("message", (topic, payload) => {
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
      if (parsed.channel === "telemetry") r.telemetry = data as Record<string, unknown>;
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
