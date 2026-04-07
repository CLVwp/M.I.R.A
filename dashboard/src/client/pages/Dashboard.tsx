import { useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, Popup, TileLayer } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { ChatPage } from "./Chat";

type RobotSnap = {
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
  listening: { text: string; ts: number; source?: string } | null;
  vision: { text: string; ts: number; source?: string } | null;
  dockerStatus?: {
    ts: number;
    services: Array<{ name: string; running: boolean; status?: string }>;
    error?: string;
  } | null;
  lastSeen: number;
};

type ContainersConfig = {
  onDashboardHost: string[];
  onRobot: string[];
  labels?: Record<string, string>;
};

type LocalDockerPayload = {
  ok: boolean;
  error?: string;
  services: Array<{
    name: string;
    label: string;
    running: boolean;
    status: string;
    present: boolean;
  }>;
};

const icon = L.icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl:
    "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
});

const SERVO_LAYOUT = [
  { idx: 0, label: "FL epaule", pin: 33 },
  { idx: 1, label: "FL genou", pin: 25 },
  { idx: 2, label: "FR epaule", pin: 26 },
  { idx: 3, label: "FR genou", pin: 32 },
  { idx: 4, label: "RL epaule", pin: 13 },
  { idx: 5, label: "RL genou", pin: 12 },
  { idx: 6, label: "RR epaule", pin: 14 },
  { idx: 7, label: "RR genou", pin: 27 },
] as const;

export function DashboardPage() {
  const [robots, setRobots] = useState<RobotSnap[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [commandAction, setCommandAction] = useState("stop");
  const [servoAngles, setServoAngles] = useState<number[]>(
    SERVO_LAYOUT.map(() => 90),
  );
  const [walkSpeed, setWalkSpeed] = useState(0.2);
  const [sequenceText, setSequenceText] = useState(
    '{"t":"cmd","m":"stand"}\n{"t":"cmd","m":"walk","v":0.2}\n{"t":"cmd","m":"speed","v":0.5}',
  );
  const [sequenceDelayMs, setSequenceDelayMs] = useState(500);
  const [controlStatus, setControlStatus] = useState<string | null>(null);
  const [containersCfg, setContainersCfg] = useState<ContainersConfig | null>(
    null,
  );
  const [localDocker, setLocalDocker] = useState<LocalDockerPayload>({
    ok: true,
    services: [],
  });
  const [videoRenderMode, setVideoRenderMode] = useState<"img" | "iframe">(
    "img",
  );

  const selected = useMemo(
    () => robots.find((r) => r.id === selectedId) ?? null,
    [robots, selectedId],
  );

  useEffect(() => {
    const es = new EventSource("/api/robots/stream");
    es.addEventListener("snapshot", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data) as {
        robots: RobotSnap[];
      };
      setRobots(data.robots);
      setSelectedId((prev) => prev ?? data.robots[0]?.id ?? null);
    });
    es.addEventListener("robot", (ev) => {
      const snap = JSON.parse((ev as MessageEvent).data) as RobotSnap;
      setRobots((prev) => {
        const i = prev.findIndex((r) => r.id === snap.id);
        if (i === -1) return [...prev, snap];
        const next = [...prev];
        next[i] = snap;
        return next;
      });
    });
    es.onerror = () => {
      es.close();
    };
    return () => es.close();
  }, []);

  useEffect(() => {
    void fetch("/api/config/containers", { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (j) setContainersCfg(j as ContainersConfig);
      });
  }, []);

  useEffect(() => {
    function load() {
      void fetch("/api/health/docker-local", { credentials: "include" })
        .then((r) => (r.ok ? r.json() : { ok: false, services: [] }))
        .then((j) => setLocalDocker(j as LocalDockerPayload));
    }
    load();
    const id = window.setInterval(load, 30_000);
    return () => window.clearInterval(id);
  }, []);

  const center: [number, number] = selected?.gps
    ? [selected.gps.lat, selected.gps.lon]
    : [48.869_867, 2.307_077];

  async function sendCommand() {
    if (!selectedId) return;
    await fetch(`/api/robots/${encodeURIComponent(selectedId)}/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ action: commandAction }),
    });
  }

  async function sendBridgePayload(payload: Record<string, unknown>) {
    if (!selectedId) return;
    const res = await fetch(`/api/robots/${encodeURIComponent(selectedId)}/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) throw new Error(data.error ?? "Erreur envoi commande");
  }

  async function sendServo(index: number) {
    try {
      const angle = Math.max(0, Math.min(180, Math.round(servoAngles[index])));
      await sendBridgePayload({ t: "srv", i: index, a: angle });
      setControlStatus(`Servo ${index} -> ${angle} deg`);
    } catch (e) {
      setControlStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function sendAllServos() {
    try {
      for (const s of SERVO_LAYOUT) {
        const angle = Math.max(0, Math.min(180, Math.round(servoAngles[s.idx])));
        await sendBridgePayload({ t: "srv", i: s.idx, a: angle });
      }
      setControlStatus("8 servos envoyes");
    } catch (e) {
      setControlStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function sendCmd(m: string, v?: number) {
    try {
      const payload: Record<string, unknown> = { t: "cmd", m };
      if (typeof v === "number") payload.v = v;
      await sendBridgePayload(payload);
      setControlStatus(`Commande envoyee: ${m}${typeof v === "number" ? ` (v=${v})` : ""}`);
    } catch (e) {
      setControlStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function runSequence() {
    const lines = sequenceText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    try {
      for (const [i, line] of lines.entries()) {
        const payload = JSON.parse(line) as Record<string, unknown>;
        await sendBridgePayload(payload);
        setControlStatus(`Sequence ${i + 1}/${lines.length} envoyee`);
        if (i < lines.length - 1) {
          await new Promise((r) => window.setTimeout(r, sequenceDelayMs));
        }
      }
      setControlStatus("Sequence terminee");
    } catch (e) {
      setControlStatus(
        `Sequence en erreur: ${e instanceof Error ? e.message : String(e)}`,
      );
    }
  }

  const streamUrl =
    selected?.meta && typeof selected.meta.streamUrl === "string"
      ? (selected.meta.streamUrl as string)
      : null;

  useEffect(() => {
    setVideoRenderMode("img");
  }, [streamUrl]);

  const robotDockerRows = useMemo(() => {
    const labels = containersCfg?.labels ?? {};
    const order = containersCfg?.onRobot?.length
      ? containersCfg.onRobot
      : (selected?.dockerStatus?.services.map((s) => s.name) ?? []);
    return order.map((name) => {
      const s = selected?.dockerStatus?.services.find((x) => x.name === name);
      return {
        name,
        label: labels[name] ?? name,
        running: s?.running ?? false,
        status: s?.status ?? (selected?.dockerStatus ? "inconnu" : "—"),
      };
    });
  }, [containersCfg, selected?.dockerStatus, selected?.id]);

  return (
    <div className="dashboard-page-wrap">
      <section
        className="docker-health"
        aria-label="État des conteneurs Docker"
      >
        <div className="docker-health__col">
          <h3 className="docker-health__title">Ce PC (dashboard)</h3>
          {!localDocker.ok && localDocker.error && (
            <p className="error small">{localDocker.error}</p>
          )}
          <ul className="docker-health__list">
            {localDocker.services.map((s) => (
              <li key={s.name} className="docker-health__item">
                <span
                  className={
                    s.running
                      ? "docker-health__dot docker-health__dot--ok"
                      : "docker-health__dot docker-health__dot--bad"
                  }
                  title={s.status}
                />
                <span className="docker-health__name">{s.label}</span>
                <span className="muted small">
                  {!s.present ? "absent" : s.status}
                </span>
              </li>
            ))}
            {localDocker.services.length === 0 && (
              <li className="muted small">
                Chargement ou Docker indisponible…
              </li>
            )}
          </ul>
        </div>
        <div className="docker-health__col">
          <h3 className="docker-health__title">
            Robot {selected ? `· ${selected.id}` : ""}
          </h3>
          {selected?.dockerStatus?.error && (
            <p className="error small">{selected.dockerStatus.error}</p>
          )}
          {!selected && (
            <p className="muted small">Sélectionnez un robot dans la liste.</p>
          )}
          {selected && !selected.dockerStatus && (
            <p className="muted small">
              Aucun rapport Docker MQTT encore (agent Pi avec{" "}
              <code>DOCKER_REPORT_SEC</code> / topic{" "}
              <code>mira/robots/{selected.id}/docker/status</code>
              ).
            </p>
          )}
          {selected && selected.dockerStatus && (
            <ul className="docker-health__list">
              {robotDockerRows.map((row) => (
                <li key={row.name} className="docker-health__item">
                  <span
                    className={
                      row.running
                        ? "docker-health__dot docker-health__dot--ok"
                        : "docker-health__dot docker-health__dot--bad"
                    }
                    title={row.status}
                  />
                  <span className="docker-health__name">{row.label}</span>
                  <span className="muted small">{row.status}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
      <div className="dashboard dashboard-3col">
        <aside className="sidebar">
          <h2>Robots</h2>
          <ul className="robot-list">
            {robots.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className={r.id === selectedId ? "robot active" : "robot"}
                  onClick={() => setSelectedId(r.id)}
                >
                  {r.id}
                  <span className="muted small">
                    {r.presence?.online === false
                      ? "hors ligne"
                      : "vu récemment"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {selected && (
            <div className="panel">
              <h3>Commande MQTT</h3>
              <select
                value={commandAction}
                onChange={(e) => setCommandAction(e.target.value)}
              >
                <option value="avance">avance</option>
                <option value="recule">recule</option>
                <option value="gauche">gauche</option>
                <option value="droite">droite</option>
                <option value="stop">stop</option>
                <option value="autopilot">autopilot</option>
                <option value="position">position</option>
              </select>
              <button type="button" onClick={() => void sendCommand()}>
                Envoyer
              </button>
              <h3>Pilotage ESP32 (JSON)</h3>
              <div className="muted small">
                <button type="button" onClick={() => void sendCmd("stand")}>
                  stand
                </button>{" "}
                <button type="button" onClick={() => void sendCmd("stand_low")}>
                  stand_low
                </button>{" "}
                <button type="button" onClick={() => void sendCmd("walk")}>
                  walk
                </button>{" "}
                <button type="button" onClick={() => void sendCmd("speed", walkSpeed)}>
                  speed
                </button>
              </div>
              <label className="muted small">
                Vitesse (v 0..1)
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={walkSpeed}
                  onChange={(e) => setWalkSpeed(Number(e.target.value))}
                />
              </label>
              <h4>Servos (0..180, pas 1)</h4>
              <p className="muted small">
                Ordre: FL epaule, FL genou, FR epaule, FR genou, RL epaule,
                RL genou, RR epaule, RR genou.
              </p>
              {SERVO_LAYOUT.map((s) => (
                <div key={s.idx} className="muted small">
                  <label>
                    {s.idx} - {s.label} (GPIO {s.pin}): {Math.round(servoAngles[s.idx])}
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={180}
                    step={1}
                    value={servoAngles[s.idx]}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setServoAngles((prev) => {
                        const next = [...prev];
                        next[s.idx] = v;
                        return next;
                      });
                    }}
                  />
                  <button type="button" onClick={() => void sendServo(s.idx)}>
                    Envoyer {s.idx}
                  </button>
                </div>
              ))}
              <button type="button" onClick={() => void sendAllServos()}>
                Envoyer les 8 servos
              </button>
              <h4>Sequence JSON (1 ligne = 1 commande)</h4>
              <textarea
                className="telemetry"
                rows={6}
                value={sequenceText}
                onChange={(e) => setSequenceText(e.target.value)}
              />
              <label className="muted small">
                Delai entre lignes (ms)
                <input
                  type="number"
                  min={0}
                  step={50}
                  value={sequenceDelayMs}
                  onChange={(e) => setSequenceDelayMs(Number(e.target.value))}
                />
              </label>
              <button type="button" onClick={() => void runSequence()}>
                Lancer sequence
              </button>
              {controlStatus && <p className="muted small">{controlStatus}</p>}
              <p className="muted small sidebar-hint">
                La transcription micro s’affiche au centre (panneau dédié).
              </p>
              <h3>GPS</h3>
              {selected.gps ? (
                <dl className="gps-summary muted small">
                  <dt>Position</dt>
                  <dd>
                    {selected.gps.lat.toFixed(6)}, {selected.gps.lon.toFixed(6)}
                  </dd>
                  {selected.gps.mock ? (
                    <dd className="gps-summary__note">Simulé (MOCK_GPS)</dd>
                  ) : (
                    <>
                      <dt>Fix</dt>
                      <dd>{selected.gps.fix === false ? "non" : "oui"}</dd>
                      {selected.gps.satellites != null && (
                        <>
                          <dt>Satellites</dt>
                          <dd>{selected.gps.satellites}</dd>
                        </>
                      )}
                    </>
                  )}
                </dl>
              ) : (
                <p className="muted small">Aucune donnée GPS (topic MQTT)</p>
              )}
              <h3>Télémétrie</h3>
              <pre className="telemetry">
                {JSON.stringify(selected.telemetry ?? {}, null, 2)}
              </pre>
            </div>
          )}
        </aside>
        <section className="dashboard-center">
          <div className="map-section">
            <h3 className="section-title">Carte GPS</h3>
            <MapContainer center={center} zoom={13} className="map">
              <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
              {robots
                .filter((r) => r.gps)
                .map((r) => (
                  <Marker
                    key={r.id}
                    position={[r.gps!.lat, r.gps!.lon]}
                    icon={icon}
                    eventHandlers={{
                      click: () => setSelectedId(r.id),
                    }}
                  >
                    <Popup>
                      <strong>{r.id}</strong>
                      <br />
                      {r.gps!.lat.toFixed(5)}, {r.gps!.lon.toFixed(5)}
                      {r.gps!.mock ? (
                        <>
                          <br />
                          <span className="muted">simulé</span>
                        </>
                      ) : (
                        <>
                          {r.gps!.satellites != null && (
                            <>
                              <br />
                              {r.gps!.satellites} sat.
                            </>
                          )}
                          {r.gps!.fix === false && (
                            <>
                              <br />
                              <span className="muted">pas de fix</span>
                            </>
                          )}
                        </>
                      )}
                    </Popup>
                  </Marker>
                ))}
            </MapContainer>
          </div>
          <div className="transcription-dedicated" aria-live="polite">
            <div className="transcription-dedicated__header">
              <span className="transcription-dedicated__label">
                Transcription micro
              </span>
              {selected && (
                <span className="transcription-dedicated__robot">
                  {selected.id}
                </span>
              )}
            </div>
            {selected?.listening?.text ? (
              <>
                <p className="transcription-dedicated__text">
                  {selected.listening.text}
                </p>
                <div className="transcription-dedicated__meta">
                  {selected.listening.source === "vosk" ? "Vosk · " : ""}
                  {new Date(
                    (selected.listening.ts ?? 0) * 1000,
                  ).toLocaleString()}
                </div>
              </>
            ) : (
              <p className="transcription-dedicated__empty muted">
                Aucune phrase reçue pour ce robot. Vérifiez le service STT sur
                la Pi et le topic MQTT{" "}
                <code>mira/robots/{selected?.id ?? "…"}/listening</code>.
              </p>
            )}
          </div>
          <div className="transcription-dedicated" aria-live="polite">
            <div className="transcription-dedicated__header">
              <span className="transcription-dedicated__label">
                Vision caméra (détections)
              </span>
              {selected && (
                <span className="transcription-dedicated__robot">
                  {selected.id}
                </span>
              )}
            </div>
            {selected?.vision?.text ? (
              <>
                <p className="transcription-dedicated__text">
                  {selected.vision.text}
                </p>
                <div className="transcription-dedicated__meta">
                  {selected.vision.source ? `${selected.vision.source} · ` : ""}
                  {new Date(
                    (selected.vision.ts ?? 0) * 1000,
                  ).toLocaleString()}
                </div>
              </>
            ) : (
              <p className="transcription-dedicated__empty muted">
                Aucune détection récente. Vérifiez mira-vision sur la Pi (topic{" "}
                <code>
                  mira/robots/{selected?.id ?? "…"}/vision/text
                </code>
                ).
              </p>
            )}
          </div>
          <div className="video-panel video-panel--center">
            <h3 className="section-title">Flux vidéo</h3>
            {streamUrl ? (
              videoRenderMode === "img" ? (
                <div className="video-media">
                  <img
                    src={streamUrl}
                    className="video-image"
                    alt="Flux caméra"
                    onError={() => setVideoRenderMode("iframe")}
                  />
                </div>
              ) : (
                <iframe
                  title="stream"
                  src={streamUrl}
                  className="video-frame"
                  scrolling="no"
                />
              )
            ) : (
              <p className="muted video-placeholder">
                Aucune URL (champ <code>streamUrl</code> dans meta MQTT)
              </p>
            )}
          </div>
        </section>
        <aside className="chat-column">
          <ChatPage embedded robotId={selectedId} />
        </aside>
      </div>
    </div>
  );
}
