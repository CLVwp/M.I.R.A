# Console M.I.R.A (Bun uniquement)

Ce dossier utilise **exclusivement Bun** comme runtime et gestionnaire de paquets (pas npm / pnpm / yarn pour les scripts du projet).

## Prérequis

- [Bun](https://bun.sh) installé
- Mosquitto (ou autre broker MQTT) sur `1883` pour la télémétrie robots
- **Ollama** pour le chat : soit installé sur la machine, soit via Docker (voir ci‑dessous)

### Ollama dans Docker (à la racine du dépôt M.I.R.A)

```bash
cd ..   # racine M.I.R.A
docker compose -f docker-compose.pc.yml up -d
```

Le port **11434** est exposé sur l’hôte : dans `dashboard/.env`, garde `OLLAMA_URL=http://127.0.0.1:11434`. Les modèles sont stockés dans le volume Docker `ollama_data`.

Première utilisation — télécharger le modèle de base et créer `mira` (sous **Git Bash** ou WSL, depuis la racine du dépôt) :

```bash
docker compose -f docker-compose.pc.yml exec ollama ollama pull qwen2.5:1.5b-instruct
docker compose -f docker-compose.pc.yml exec ollama ollama create mira -f /config/Modelfile
```

Sous **Windows**, le GPU (AMD/NVIDIA) dans le conteneur Ollama n’est pas toujours utilisé selon Docker Desktop ; l’inférence peut retomber sur le **CPU** (plus lent mais fonctionnel).

Alternative : installer [Ollama](https://ollama.com) **nativement** sur Windows pour un meilleur accès GPU.

## Installation

```bash
cd dashboard
bun install
cp .env.example .env
# éditer .env (au minimum BETTER_AUTH_SECRET)
echo y | bun x --bun auth@latest migrate --config src/auth.ts
```

## Développement

Deux processus : API Bun (3000) + Vite (5173), lancés par un seul script Bun :

```bash
bun run dev
```

Ouvrir `http://localhost:5173`.

### Micro et reconnaissance vocale (STT)

- **Dans le panneau chat du dashboard**, le bouton **Micro** utilise **Web Speech API** (Chrome / Edge recommandés). Au clic, le navigateur demande l’accès au **micro** via `getUserMedia`, puis lance la reconnaissance vocale **côté navigateur** (souvent un service cloud du fournisseur du navigateur, selon les réglages).
- Ce n’est **pas** le conteneur Docker **`mira-stt`** du dépôt racine. **`mira-stt`** est le service **Vosk + micro** prévu pour la **Raspberry Pi** (audio système, MQTT, mot de réveil « mira », etc.) : pipeline **robot**, pas branché sur l’UI web actuelle.
- Pour qu’un jour le chat utilise le même moteur que la Pi, il faudrait une **API HTTP ou WebSocket** qui envoie l’audio au serveur, puis au service STT (gros chantier).

### Micro du robot (Vosk) dans le panneau gauche

Quand le service **`mira-stt`** tourne sur la Raspberry avec le micro branché, chaque phrase reconnue est publiée sur MQTT : `mira/robots/{ROBOT_ID}/listening`. Le dashboard affiche le dernier texte sous **« Micro robot (Vosk) »** pour le robot sélectionné (même `ROBOT_ID` que la variable d’environnement du conteneur STT, ex. `mira-robot` dans `docker-compose.rpi.yml`).

Ce n’est **pas** de l’audio brut dans le navigateur : c’est la **transcription** (texte), en temps quasi réel via le flux SSE existant.

## Production (build Bun)

```bash
bun run build
NODE_ENV=production PORT=3000 bun dist/server/index.js
```

Le serveur sert le front depuis `dist/client` et l’API sur le même port.

## Commandes utiles (toutes via Bun)

| Commande                                               | Rôle                          |
| ------------------------------------------------------ | ----------------------------- |
| `bun run dev`                                          | API + Vite                    |
| `bun run dev:server`                                   | API seule                     |
| `bun run dev:client`                                   | Vite seul (`bun --bun vite`)  |
| `bun run build`                                        | Build client + bundle serveur |
| `bun x --bun auth@latest migrate --config src/auth.ts` | Migrations Better Auth        |

---

## Raspberry Pi — installation pour les tests sur la carte

Hypothèses : **Raspberry Pi OS 64 bits** (Bookworm ou plus récent), accès SSH ou clavier, dépôt **M.I.R.A** déjà copié ou cloné (ex. `~/M.I.R.A`).

### 1. Système et outils de base

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl ca-certificates python3 python3-venv python3-pip
```

### 2. Docker Engine + plugin Compose

Les conteneurs du projet passent par Docker (stack **Pi** : Mosquitto, STT, etc. ; stack **PC** : Ollama seul — voir `docker-compose.rpi.yml` / `docker-compose.pc.yml`).

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

Déconnexion / reconnexion SSH (ou `newgrp docker`) pour que le groupe `docker` soit pris en compte, puis vérifier :

```bash
docker --version
docker compose version
```

### 3. Bun (runtime du dashboard)

Script officiel (Linux **arm64** / **aarch64** pris en charge) :

```bash
curl -fsSL https://bun.sh/install | bash
# puis recharger le shell ou :
source ~/.bashrc   # ou le fichier affiché par l’installateur
bun --version
```

### 4. Services Docker sur la Pi (racine du dépôt)

```bash
cd ~/M.I.R.A   # adapter le chemin
docker compose -f docker-compose.rpi.yml up -d
docker compose -f docker-compose.rpi.yml ps
```

Optionnel : fichier **`.env`** à la racine pour `OLLAMA_PC_HOST` (IP du PC où tourne Ollama) et `RPI_STREAM_URL` (flux vidéo pour le dashboard).

**Ollama** : en général sur le **PC** (`docker compose -f docker-compose.pc.yml up -d` sur la machine Windows/Linux du dashboard). Si tu lances Ollama **sur la Pi** aussi, fais-le seulement si la carte a assez de RAM ; crée alors le modèle `mira` avec les commandes `docker compose -f docker-compose.pc.yml exec ollama …` depuis la Pi.

### 5. Dashboard (Bun) — première fois

```bash
cd ~/M.I.R.A/dashboard
bun install
cp .env.example .env
```

Éditer **`.env`** au minimum :

- `BETTER_AUTH_SECRET` : chaîne aléatoire **≥ 32 caractères**
- `BETTER_AUTH_URL` : `http://localhost:3000` si tu ouvres le navigateur **sur la Pi** ; si tu accèdes à l’UI depuis un autre PC, mets l’URL du Pi (ex. `http://192.168.1.x:3000`) et la même logique pour `CLIENT_ORIGIN` (ex. `http://192.168.1.x:5173`)

Migrations Better Auth :

```bash
echo y | bun x --bun auth@latest migrate --config src/auth.ts
```

Lancer en dev (API + Vite) :

```bash
bun run dev
```

Puis ouvrir `http://localhost:5173` sur la Pi, ou `http://<IP_DE_LA_PI>:5173` depuis le réseau.

**Accès depuis un autre PC sur le LAN** : Vite doit écouter sur toutes les interfaces. En attendant une config dédiée, tu peux lancer le front en mode exposé :

```bash
# Terminal 1 — API
bun run dev:server

# Terminal 2 — Vite avec écoute réseau
bun --bun vite --host 0.0.0.0 --port 5173
```

Adapte `CLIENT_ORIGIN` et `BETTER_AUTH_URL` dans `.env` à l’URL réelle (IP + ports) que le navigateur utilise.

### 6. Mode production sur la Pi (un seul port, sans Vite)

```bash
cd ~/M.I.R.A/dashboard
bun run build
NODE_ENV=production PORT=3000 bun dist/server/index.js
```

Ouvre `http://<IP_DE_LA_PI>:3000` (pense à aligner `BETTER_AUTH_URL` et `CLIENT_ORIGIN` sur cette URL).

### 7. Agent Python « robot » (MQTT de test, GPS simulé)

Utile pour voir **robots / carte / télémétrie** sans matériel réel :

```bash
cd ~/M.I.R.A/rpi-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MQTT_BROKER=127.0.0.1
export MQTT_PORT=1883
export MOCK_GPS=1
python agent.py
```

Pour un `ROBOT_ID` fixe : `export ROBOT_ID=my-pi-01`.

### 8. Pare-feu (optionnel)

Si **ufw** est actif :

```bash
sudo ufw allow 22/tcp
sudo ufw allow 3000/tcp
sudo ufw allow 5173/tcp
sudo ufw allow 1883/tcp
# Ollama si accès direct depuis le LAN :
sudo ufw allow 11434/tcp
sudo ufw reload
```

### 9. Rappel des ports

| Port  | Service                                   |
| ----- | ----------------------------------------- |
| 1883  | Mosquitto (MQTT)                          |
| 3000  | API Bun (dashboard, prod ou `dev:server`) |
| 5173  | Vite (dev uniquement)                     |
| 11434 | Ollama (conteneur)                        |

### 10. Stack Python / Docker du robot (hors dashboard)

Le reste du dépôt se lance avec **`docker compose -f docker-compose.rpi.yml`** sur la **Raspberry** (STT, TTS, vision, bridge, Mosquitto, agent). Sur le **PC**, Ollama seul : **`docker compose -f docker-compose.pc.yml`** (voir les fichiers à la racine du projet).

#### PC hôte du dashboard (machine où tourne le dashboard)

| Conteneur        | Rôle (libellé)   |
| ---------------- | ---------------- |
| `mira-mosquitto` | MQTT (Mosquitto) |
| `mira-ollama`    | LLM (Ollama)     |

#### Robot (Raspberry Pi / machine embarquée)

| Conteneur       | Rôle (libellé)   |
| --------------- | ---------------- |
| `mira-stt`      | STT (Vosk)       |
| `mira-tts`      | TTS              |
| `mira-vision`   | Vision           |
| `mira-bridge`   | Bridge UART      |

La liste affichée dans le dashboard est pilotée par `config/service-containers.json`.
