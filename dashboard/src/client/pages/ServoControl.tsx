import { useEffect, useMemo, useState } from "react";

type RobotSnap = {
  id: string;
  presence: { ts: number; online?: boolean } | null;
};

const SERVO_LAYOUT = [
  { idx: 0, label: "FL epaule", pin: 33, x: 23, y: 28 },
  { idx: 1, label: "FL genou", pin: 25, x: 12, y: 52 },
  { idx: 2, label: "FR epaule", pin: 26, x: 77, y: 28 },
  { idx: 3, label: "FR genou", pin: 32, x: 88, y: 52 },
  { idx: 4, label: "RL epaule", pin: 13, x: 23, y: 66 },
  { idx: 5, label: "RL genou", pin: 12, x: 12, y: 88 },
  { idx: 6, label: "RR epaule", pin: 14, x: 77, y: 66 },
  { idx: 7, label: "RR genou", pin: 27, x: 88, y: 88 },
] as const;

type Pt = { x: number; y: number };

const LEG_ROOTS = {
  FL: { x: 230, y: 150 },
  FR: { x: 370, y: 150 },
  RL: { x: 230, y: 210 },
  RR: { x: 370, y: 210 },
} as const;

const FEMUR_LEN = 88;
const TIBIA_LEN = 78;

function degToRad(d: number): number {
  return (d * Math.PI) / 180;
}

function clampAngle(a: number): number {
  return Math.max(0, Math.min(180, Math.round(a)));
}

function legPoints(
  root: Pt,
  side: "left" | "right",
  shoulderDeg: number,
  kneeDeg: number,
): { knee: Pt; foot: Pt } {
  const shoulder = clampAngle(shoulderDeg);
  const knee = clampAngle(kneeDeg);

  // Convention demandee: a 90 deg, epaule->genou est perpendiculaire au body,
  // donc vertical vers le bas dans ce schema (axe +Y).
  // On garde un miroir gauche/droite pour la variation autour de 90.
  const shoulderOffset = (shoulder - 90) * 0.9;
  const femurAngle = 90 + (side === "left" ? -shoulderOffset : shoulderOffset);

  // Le genou plie le tibia par rapport au femur.
  const bend = ((knee - 90) / 90) * 70;
  const tibiaAngle =
    femurAngle + (side === "left" ? 38 + bend : -(38 + bend));

  const kx = root.x + FEMUR_LEN * Math.cos(degToRad(femurAngle));
  const ky = root.y + FEMUR_LEN * Math.sin(degToRad(femurAngle));
  const fx = kx + TIBIA_LEN * Math.cos(degToRad(tibiaAngle));
  const fy = ky + TIBIA_LEN * Math.sin(degToRad(tibiaAngle));

  return { knee: { x: kx, y: ky }, foot: { x: fx, y: fy } };
}

export function ServoControlPage() {
  const [robots, setRobots] = useState<RobotSnap[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [angles, setAngles] = useState<number[]>(SERVO_LAYOUT.map(() => 90));
  const [status, setStatus] = useState<string | null>(null);

  const selected = useMemo(
    () => robots.find((r) => r.id === selectedId) ?? null,
    [robots, selectedId],
  );

  const kFL = legPoints(LEG_ROOTS.FL, "left", angles[0], angles[1]);
  const kFR = legPoints(LEG_ROOTS.FR, "right", angles[2], angles[3]);
  const kRL = legPoints(LEG_ROOTS.RL, "left", angles[4], angles[5]);
  const kRR = legPoints(LEG_ROOTS.RR, "right", angles[6], angles[7]);

  useEffect(() => {
    const es = new EventSource("/api/robots/stream");
    es.addEventListener("snapshot", (ev) => {
      const data = JSON.parse((ev as MessageEvent).data) as { robots: RobotSnap[] };
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
    es.onerror = () => es.close();
    return () => es.close();
  }, []);

  async function sendPayload(payload: Record<string, unknown>) {
    if (!selectedId) return;
    const res = await fetch(`/api/robots/${encodeURIComponent(selectedId)}/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload),
    });
    const data = (await res.json()) as { error?: string };
    if (!res.ok) throw new Error(data.error ?? "Erreur commande");
  }

  async function sendServo(idx: number) {
    try {
      const a = Math.max(0, Math.min(180, Math.round(angles[idx])));
      await sendPayload({ t: "srv", i: idx, a });
      setStatus(`Servo ${idx} -> ${a} deg`);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function sendAll() {
    try {
      for (const s of SERVO_LAYOUT) {
        const a = Math.max(0, Math.min(180, Math.round(angles[s.idx])));
        await sendPayload({ t: "srv", i: s.idx, a });
      }
      setStatus("Pose 8 servos envoyee");
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="servo-page">
      <aside className="servo-robots">
        <h2>Robot cible</h2>
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
                  {r.presence?.online === false ? "hors ligne" : "vu recemment"}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {selected && <p className="muted small">Selection: {selected.id}</p>}
        {status && <p className="muted small">{status}</p>}
        <button type="button" onClick={() => void sendAll()}>
          Envoyer les 8 servos
        </button>
      </aside>

      <section className="servo-canvas">
        <h2>Quadrupede - controle articulation</h2>
        <p className="muted small">
          Ordre: FL epaule, FL genou, FR epaule, FR genou, RL epaule, RL genou, RR
          epaule, RR genou.
        </p>
        <div className="servo-diagram">
          <svg viewBox="0 0 600 360" className="servo-robot-svg" aria-hidden="true">
            <rect x="190" y="120" width="220" height="120" rx="26" fill="#1f2733" />
            <circle cx={LEG_ROOTS.FL.x} cy={LEG_ROOTS.FL.y} r="10" fill="#58a6ff" />
            <circle cx={LEG_ROOTS.FR.x} cy={LEG_ROOTS.FR.y} r="10" fill="#58a6ff" />
            <circle cx={LEG_ROOTS.RL.x} cy={LEG_ROOTS.RL.y} r="10" fill="#58a6ff" />
            <circle cx={LEG_ROOTS.RR.x} cy={LEG_ROOTS.RR.y} r="10" fill="#58a6ff" />

            <line x1={LEG_ROOTS.FL.x} y1={LEG_ROOTS.FL.y} x2={kFL.knee.x} y2={kFL.knee.y} stroke="#8b949e" strokeWidth="8" />
            <line x1={kFL.knee.x} y1={kFL.knee.y} x2={kFL.foot.x} y2={kFL.foot.y} stroke="#8b949e" strokeWidth="8" />

            <line x1={LEG_ROOTS.FR.x} y1={LEG_ROOTS.FR.y} x2={kFR.knee.x} y2={kFR.knee.y} stroke="#8b949e" strokeWidth="8" />
            <line x1={kFR.knee.x} y1={kFR.knee.y} x2={kFR.foot.x} y2={kFR.foot.y} stroke="#8b949e" strokeWidth="8" />

            <line x1={LEG_ROOTS.RL.x} y1={LEG_ROOTS.RL.y} x2={kRL.knee.x} y2={kRL.knee.y} stroke="#8b949e" strokeWidth="8" />
            <line x1={kRL.knee.x} y1={kRL.knee.y} x2={kRL.foot.x} y2={kRL.foot.y} stroke="#8b949e" strokeWidth="8" />

            <line x1={LEG_ROOTS.RR.x} y1={LEG_ROOTS.RR.y} x2={kRR.knee.x} y2={kRR.knee.y} stroke="#8b949e" strokeWidth="8" />
            <line x1={kRR.knee.x} y1={kRR.knee.y} x2={kRR.foot.x} y2={kRR.foot.y} stroke="#8b949e" strokeWidth="8" />

            <circle cx={kFL.knee.x} cy={kFL.knee.y} r="6" fill="#3fb950" />
            <circle cx={kFR.knee.x} cy={kFR.knee.y} r="6" fill="#3fb950" />
            <circle cx={kRL.knee.x} cy={kRL.knee.y} r="6" fill="#3fb950" />
            <circle cx={kRR.knee.x} cy={kRR.knee.y} r="6" fill="#3fb950" />
          </svg>

          {SERVO_LAYOUT.map((s) => (
            <div
              key={s.idx}
              className="servo-node"
              style={{ left: `${s.x}%`, top: `${s.y}%` }}
            >
              <div className="servo-node__title">
                {s.idx} - {s.label} (GPIO {s.pin})
              </div>
              <input
                type="range"
                min={0}
                max={180}
                step={1}
                value={angles[s.idx]}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setAngles((prev) => {
                    const next = [...prev];
                    next[s.idx] = v;
                    return next;
                  });
                }}
              />
              <div className="servo-node__row">
                <span>{Math.round(angles[s.idx])} deg</span>
                <button type="button" onClick={() => void sendServo(s.idx)}>
                  Envoyer
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

