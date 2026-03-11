"""
M.I.R.A — Module TTS (Text-to-Speech)
Écoute le topic MQTT « mira/tts/say » et lit les messages à voix haute
via gTTS (Google Text-to-Speech) pour une voix naturelle en français.
"""

import os
import sys
import subprocess
import tempfile
import threading
import queue
from gtts import gTTS
import paho.mqtt.client as mqtt

# ── Configuration ──────────────────────────────────────────────
MQTT_BROKER = os.getenv("MQTT_BROKER", "mira-mosquitto")
MQTT_PORT   = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC  = os.getenv("MQTT_TOPIC", "mira/tts/say")

TTS_LANG    = os.getenv("TTS_LANG", "fr")
TTS_SLOW    = os.getenv("TTS_SLOW", "false").lower() == "true"

# ── Couleurs terminal ─────────────────────────────────────────
C_RESET  = "\033[0m"
C_GREEN  = "\033[1;32m"
C_CYAN   = "\033[0;36m"
C_YELLOW = "\033[1;33m"
C_RED    = "\033[1;31m"

# ── File d'attente TTS ────────────────────────────────────────
tts_queue: queue.Queue[str] = queue.Queue()


def speak(text):
    """Génère l'audio avec gTTS et le joue via mpg123."""
    tmp_path = None
    try:
        # Générer le fichier audio MP3
        tts = gTTS(text=text, lang=TTS_LANG, slow=TTS_SLOW)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        tts.save(tmp_path)

        # Lire le fichier audio avec mpg123
        subprocess.run(
            ["mpg123", "-q", tmp_path],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        print(f"{C_RED}[TTS] ERREUR : 'mpg123' non trouvé. "
              f"Installez-le avec : sudo apt install mpg123{C_RESET}")
    except Exception as e:
        print(f"{C_RED}[TTS] Erreur : {e}{C_RESET}")
    finally:
        # Nettoyage du fichier temporaire
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def tts_worker():
    """Thread dédié qui lit les messages en séquence."""
    print(f"{C_GREEN}[TTS] Moteur gTTS prêt "
          f"(lang={TTS_LANG}, slow={TTS_SLOW}){C_RESET}")

    while True:
        text = tts_queue.get()
        if text is None:
            break
        preview = text[:80] + ("..." if len(text) > 80 else "")
        print(f"{C_GREEN}[TTS] 🔊 Lecture : \"{preview}\"{C_RESET}")
        speak(text)
        print(f"{C_CYAN}[TTS] ✅ Lecture terminée.{C_RESET}")


# ── Callbacks MQTT ────────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"{C_GREEN}[MQTT] Connecté au broker. "
              f"Abonnement à « {MQTT_TOPIC} »...{C_RESET}")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"{C_RED}[MQTT] Échec de connexion (code {rc}){C_RESET}")


def on_message(client, userdata, msg):
    text = msg.payload.decode("utf-8").strip()
    if not text:
        return
    print(f"{C_CYAN}[MQTT] Message reçu sur « {msg.topic} » "
          f"({len(text)} caractères){C_RESET}")
    tts_queue.put(text)


# ── Point d'entrée ────────────────────────────────────────────
def main():
    # Démarrer le worker TTS
    worker = threading.Thread(target=tts_worker, daemon=True)
    worker.start()

    # Connexion MQTT
    print(f"{C_CYAN}[INIT] Connexion MQTT → {MQTT_BROKER}:{MQTT_PORT}...{C_RESET}")

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:
        client = mqtt.Client()

    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        print(f"{C_RED}[ERREUR] Impossible de se connecter au broker : {e}{C_RESET}")
        sys.exit(1)

    print(f"{C_GREEN}>>> M.I.R.A TTS en écoute...{C_RESET}")
    client.loop_forever()


if __name__ == "__main__":
    main()
