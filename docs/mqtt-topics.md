# Topics MQTT M.I.R.A (dashboard + robots)

Convention : `{id}` = identifiant robot (ex. hostname).

| Domaine | Topic | Contenu (JSON) |
|--------|--------|----------------|
| Métadonnées | `mira/robots/{id}/meta` | `hostname`, `version`, `capabilities`, `streamUrl` (URL MJPEG/HLS/WebRTC), etc. (retained recommandé) |
| Présence | `mira/robots/{id}/presence` | `{ "ts": number, "online"?: boolean }` + LWT hors ligne |
| Télémétrie | `mira/robots/{id}/telemetry` | champs libres (batterie, IMU, etc.) |
| GPS | `mira/robots/{id}/gps` | `{ "lat", "lon", "acc"?, "ts"?, "mock"?, "fix"?, "satellites"? }` — `fix` / `satellites` renseignés par `mira-rpi-agent` en mode NMEA réel |
| Micro / STT (Vosk) | `mira/robots/{id}/listening` | `{ "text": string, "ts": number, "source": "vosk" }` — transcription remontée au dashboard |
| Docker (agent Pi) | `mira/robots/{id}/docker/status` | `{ "ts": number, "services": [ { "name": string, "running": boolean, "status": string } ], "error"?: string }` — état des conteneurs attendus sur le robot (périodique, ex. toutes les 30 s) |
| Ordres (nouveau) | `mira/robots/{id}/bridge/ordres` | `{"action":"avance"}` (même contrat que le bridge historique) |
| Ordres (historique) | `mira/bridge/ordres` | idem ; le dashboard publie aussi ici pour compatibilité mono-robot |

Vision texte existante : `mira/vision/output` — à préfixer par robot en multi-unités (`mira/robots/{id}/vision/text`).

Flux vidéo (dashboard) : le conteneur **`mira-vision`** peut servir un **MJPEG** sur `http://<IP_PI>:8080/stream` (voir `STREAM_MJPEG_*` dans `vision.py`) ; l’URL doit être copiée dans **`RPI_STREAM_URL`** (meta MQTT via `mira-rpi-agent`).

Schéma commande HTTP/API : `dashboard/schemas/robot-command.json`.
