#!/usr/bin/env python3
"""
Agent Raspberry — présence MQTT + GPS (réel ou simulé) pour le dashboard M.I.R.A.

Variables d'environnement :
  MQTT_BROKER, MQTT_PORT, ROBOT_ID
  MOCK_GPS      "1" = position simulée ; "0" + GPS_SERIAL = NMEA sur le port série
  LAT, LON      repli tant qu’il n’y a pas de fix GPS
  GPS_SERIAL    port dans le conteneur (ex. /dev/gps0 après devices: ttyUSB0)
  GPS_BAUD      défaut 9600 (L80 / CP2102 courant)
  ROBOT_DOCKER_CONTAINERS, DOCKER_REPORT_SEC
"""

import json
import os
import random
import re
import socket
import subprocess
import threading
import time

import paho.mqtt.client as mqtt

BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
PORT = int(os.getenv("MQTT_PORT", "1883"))
ROBOT_ID = os.getenv("ROBOT_ID", socket.gethostname())
MOCK_GPS = os.getenv("MOCK_GPS", "1") == "1"
LAT0 = float(os.getenv("LAT", "48.869867"))
LON0 = float(os.getenv("LON", "2.307077"))
INTERVAL = float(os.getenv("HEARTBEAT_SEC", "5"))
GPS_SERIAL = os.getenv("GPS_SERIAL", "").strip()
GPS_BAUD = int(os.getenv("GPS_BAUD", "9600"))
ROBOT_DOCKER_CONTAINERS = [
    x.strip()
    for x in os.getenv(
        "ROBOT_DOCKER_CONTAINERS",
        "mira-stt,mira-tts,mira-vision,mira-bridge",
    ).split(",")
    if x.strip()
]
DOCKER_REPORT_SEC = float(os.getenv("DOCKER_REPORT_SEC", "30"))

_gps_lock = threading.Lock()
_gps_lat = LAT0
_gps_lon = LON0
_gps_has_fix = False
_gps_sats: int | None = None


def _nmea_coord_to_deg(raw: str, hemi: str) -> float:
    if not raw or len(raw) < 3:
        return 0.0
    raw = raw.strip()
    dot = raw.find(".")
    if dot < 2:
        return 0.0
    deg_len = 2 if hemi in ("N", "S") else 3
    try:
        deg = int(raw[:deg_len])
        minutes = float(raw[deg_len:])
        v = deg + minutes / 60.0
        if hemi in ("S", "W"):
            v = -v
        return v
    except ValueError:
        return 0.0


def _apply_nmea_fix(lat: float, lon: float, sats: int | None) -> None:
    global _gps_lat, _gps_lon, _gps_has_fix, _gps_sats
    with _gps_lock:
        _gps_lat, _gps_lon = lat, lon
        _gps_has_fix = True
        if sats is not None:
            _gps_sats = sats


def _parse_and_apply_line(line: str) -> None:
    line = line.strip()
    if not line.startswith("$"):
        return
    parts = line.split(",")
    if len(parts) < 7:
        return
    head = parts[0].upper()
    if "RMC" in head and len(parts) >= 7:
        if parts[2] != "A":
            return
        lat = _nmea_coord_to_deg(parts[3], parts[4])
        lon = _nmea_coord_to_deg(parts[5], parts[6])
        if abs(lat) < 1e-6 and abs(lon) < 1e-6:
            return
        _apply_nmea_fix(lat, lon, None)
        return
    if "GGA" in head and len(parts) >= 8:
        try:
            qual = int(parts[6] or "0")
        except ValueError:
            qual = 0
        if qual == 0:
            return
        lat = _nmea_coord_to_deg(parts[2], parts[3])
        lon = _nmea_coord_to_deg(parts[4], parts[5])
        if abs(lat) < 1e-6 and abs(lon) < 1e-6:
            return
        sats = None
        try:
            if parts[7]:
                sats = int(parts[7])
        except ValueError:
            pass
        _apply_nmea_fix(lat, lon, sats)


def _gps_reader_loop():
    global _gps_has_fix
    try:
        import serial
    except ImportError:
        print("[GPS] pyserial manquant")
        return
    while True:
        try:
            ser = serial.Serial(GPS_SERIAL, GPS_BAUD, timeout=2)
            print(f"[GPS] Ouvert {GPS_SERIAL} @ {GPS_BAUD}")
            buf = ""
            while True:
                chunk = ser.read(256)
                if not chunk:
                    continue
                buf += chunk.decode("ascii", errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if re.match(r"^\$GP|^\$GN", line.strip()):
                        _parse_and_apply_line(line.strip())
        except Exception as e:
            print(f"[GPS] Erreur série ({e}) — nouvel essai dans 5s")
            with _gps_lock:
                _gps_has_fix = False
            time.sleep(5)


def collect_docker_status(names):
    out = {"ts": time.time(), "services": []}
    try:
        for name in names:
            r = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", name],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if r.returncode != 0:
                out["services"].append(
                    {"name": name, "running": False, "status": "absent"}
                )
            else:
                st = (r.stdout or "").strip()
                out["services"].append(
                    {"name": name, "running": st == "running", "status": st}
                )
    except FileNotFoundError:
        out["error"] = "docker_cli_missing"
    except Exception as e:
        out["error"] = str(e)
    return out


def main():
    if not MOCK_GPS and GPS_SERIAL:
        threading.Thread(target=_gps_reader_loop, daemon=True).start()
        print(f"[GPS] Thread NMEA sur {GPS_SERIAL} (MOCK_GPS=0)")
    elif not MOCK_GPS and not GPS_SERIAL:
        print(
            "[GPS] MOCK_GPS=0 mais GPS_SERIAL vide — position LAT/LON jusqu’à config "
            "(compose: devices + GPS_SERIAL=/dev/gps0)"
        )

    cid = f"mira-agent-{ROBOT_ID}"
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=cid)
    except (AttributeError, TypeError):
        client = mqtt.Client(client_id=cid)

    will = json.dumps({"ts": time.time(), "online": False})
    client.will_set(f"mira/robots/{ROBOT_ID}/presence", will, qos=0, retain=True)

    client.connect(BROKER, PORT, 60)
    client.loop_start()

    meta = {
        "hostname": socket.gethostname(),
        "version": "rpi-agent/1",
        "capabilities": ["telemetry", "gps", "bridge"],
        "streamUrl": os.getenv("STREAM_URL", ""),
    }
    client.publish(
        f"mira/robots/{ROBOT_ID}/meta",
        json.dumps(meta),
        qos=0,
        retain=True,
    )

    lat, lon = LAT0, LON0
    last_docker_report = 0.0
    try:
        while True:
            now = time.time()
            if ROBOT_DOCKER_CONTAINERS and (
                now - last_docker_report >= DOCKER_REPORT_SEC
            ):
                payload = collect_docker_status(ROBOT_DOCKER_CONTAINERS)
                client.publish(
                    f"mira/robots/{ROBOT_ID}/docker/status",
                    json.dumps(payload),
                    qos=0,
                    retain=False,
                )
                last_docker_report = now
            client.publish(
                f"mira/robots/{ROBOT_ID}/presence",
                json.dumps({"ts": now, "online": True}),
                qos=0,
                retain=False,
            )

            gps_fix_snap = None
            gps_sats_snap = None
            if MOCK_GPS:
                lat += random.uniform(-0.0003, 0.0003)
                lon += random.uniform(-0.0003, 0.0003)
            elif GPS_SERIAL:
                with _gps_lock:
                    gps_fix_snap = _gps_has_fix
                    gps_sats_snap = _gps_sats
                    if gps_fix_snap:
                        lat, lon = _gps_lat, _gps_lon
                    else:
                        lat, lon = LAT0, LON0
            else:
                lat, lon = LAT0, LON0

            acc = 5.0 if MOCK_GPS or not GPS_SERIAL else (
                8.0 if gps_fix_snap else 50.0
            )
            gps_payload: dict = {
                "lat": lat,
                "lon": lon,
                "acc": acc,
                "ts": now,
                "mock": MOCK_GPS,
            }
            if not MOCK_GPS and GPS_SERIAL:
                gps_payload["fix"] = bool(gps_fix_snap)
                if gps_sats_snap is not None:
                    gps_payload["satellites"] = gps_sats_snap

            client.publish(
                f"mira/robots/{ROBOT_ID}/gps",
                json.dumps(gps_payload),
                qos=0,
                retain=False,
            )
            client.publish(
                f"mira/robots/{ROBOT_ID}/telemetry",
                json.dumps(
                    {
                        "battery_pct": round(70 + random.uniform(-5, 5), 1),
                        "uptime_sec": int(now),
                        "mock": MOCK_GPS,
                        "gps_fix": gps_fix_snap
                        if (not MOCK_GPS and GPS_SERIAL)
                        else None,
                        "gps_satellites": gps_sats_snap
                        if (not MOCK_GPS and GPS_SERIAL)
                        else None,
                    },
                ),
                qos=0,
                retain=False,
            )
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
