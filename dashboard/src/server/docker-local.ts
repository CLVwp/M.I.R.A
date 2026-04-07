import { readFileSync } from "node:fs";
import { join } from "node:path";

export type ServiceContainersConfig = {
  onDashboardHost: string[];
  onRobot: string[];
  labels?: Record<string, string>;
};

function loadConfig(): ServiceContainersConfig {
  const path = join(process.cwd(), "config/service-containers.json");
  try {
    return JSON.parse(
      readFileSync(path, "utf-8"),
    ) as ServiceContainersConfig;
  } catch {
    return {
      onDashboardHost: ["mira-mosquitto", "mira-ollama"],
      onRobot: [
        "mira-stt",
        "mira-tts",
        "mira-vision",
        "mira-bridge",
      ],
    };
  }
}

export function loadServiceContainersConfig(): ServiceContainersConfig {
  return loadConfig();
}

async function inspectContainer(
  name: string,
): Promise<{
  name: string;
  running: boolean;
  status: string;
  present: boolean;
}> {
  try {
    const proc = Bun.spawn(
      ["docker", "inspect", "-f", "{{.State.Status}}", name],
      {
        stdout: "pipe",
        stderr: "pipe",
      },
    );
    const code = await proc.exited;
    const out = await new Response(proc.stdout).text();
    const status = out.trim();
    if (code !== 0) {
      return {
        name,
        running: false,
        status: "absent",
        present: false,
      };
    }
    return {
      name,
      running: status === "running",
      status,
      present: true,
    };
  } catch {
    return {
      name,
      running: false,
      status: "error",
      present: false,
    };
  }
}

export type LocalDockerService = {
  name: string;
  label: string;
  running: boolean;
  status: string;
  present: boolean;
};

export async function getDockerHealthLocal(): Promise<{
  ok: boolean;
  error?: string;
  services: LocalDockerService[];
}> {
  const cfg = loadConfig();
  const labels = cfg.labels ?? {};
  try {
    const services: LocalDockerService[] = [];
    for (const name of cfg.onDashboardHost) {
      const s = await inspectContainer(name);
      services.push({
        name,
        label: labels[name] ?? name,
        running: s.running,
        status: s.status,
        present: s.present,
      });
    }
    return { ok: true, services };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return {
      ok: false,
      error: msg,
      services: [],
    };
  }
}
