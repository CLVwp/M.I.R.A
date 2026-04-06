import os
import sys
import json
import time
import threading
import paho.mqtt.client as mqtt

# ── Configuration ──────────────────────────────────────────────
MQTT_BROKER = os.getenv("MQTT_BROKER", "mira-mosquitto")
MQTT_PORT   = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_ORDRES   = os.getenv("MQTT_TOPIC_ORDRES", "mira/bridge/ordres")
MQTT_TOPIC_FEEDBACK = os.getenv("MQTT_TOPIC_FEEDBACK", "mira/bridge/feedback")

UART_PORT = os.getenv("UART_PORT", "/dev/ttyUSB0")
UART_BAUD = int(os.getenv("UART_BAUD", "115200"))

# ── Couleurs terminal ─────────────────────────────────────────
C_RESET  = "\033[0m"
C_GREEN  = "\033[1;32m"
C_CYAN   = "\033[0;36m"
C_YELLOW = "\033[1;33m"
C_RED    = "\033[1;31m"
C_BLUE   = "\033[1;34m"
C_MAGENTA = "\033[1;35m"

# ── Mapping commande vocale → trame UART ──────────────────────
# Chaque clé correspond à un mot détecté par detect_motor_command() dans stt.py
# La valeur est le mot-clé envoyé dans la trame <CMD:...>
COMMAND_MAP = {
    "avance":     "FORWARD",
    "avancer":    "FORWARD",
    "recule":     "BACKWARD",
    "reculer":    "BACKWARD",
    "recul":      "BACKWARD",
    "gauche":     "LEFT",
    "droite":     "RIGHT",
    "stop":       "STOP",
    "stoppe":     "STOP",
    "arrête":     "STOP",
    "arreter":    "STOP",
    "autopilot":  "AUTOPILOT",
    "autopilote": "AUTOPILOT",
    "position":   "POSITION",
}

# ── Port série ────────────────────────────────────────────────
serial_port = None

def init_serial():
    """Tente d'ouvrir le port série vers l'ESP32."""
    global serial_port
    try:
        import serial
        serial_port = serial.Serial(UART_PORT, UART_BAUD, timeout=1)
        print(f"{C_GREEN}[UART] Port série ouvert : {UART_PORT} @ {UART_BAUD} baud{C_RESET}")
        return True
    except ImportError:
        print(f"{C_RED}[ERREUR] pyserial non installé. pip install pyserial{C_RESET}")
        return False
    except Exception as e:
        print(f"{C_RED}[ERREUR] Impossible d'ouvrir {UART_PORT} : {e}{C_RESET}")
        print(f"{C_YELLOW}[UART] Mode DEBUG activé — les trames seront loggées sans envoi série.{C_RESET}")
        return False

def send_uart(frame: str):
    """Envoie une trame sur le port série (ou logge en mode debug)."""
    if serial_port and serial_port.is_open:
        try:
            serial_port.write(frame.encode("utf-8"))
            print(f"{C_GREEN}[UART ►] {frame.strip()}{C_RESET}")
        except Exception as e:
            print(f"{C_RED}[ERREUR UART] Échec d'envoi : {e}{C_RESET}")
    else:
        # Mode debug : pas de port série, on logge seulement
        print(f"{C_YELLOW}[UART DEBUG ►] {frame.strip()}{C_RESET}")

def uart_reader(mqtt_client):
    """Thread qui lit les réponses de l'ESP32 et les publie sur MQTT."""
    while True:
        try:
            if serial_port and serial_port.is_open and serial_port.in_waiting > 0:
                line = serial_port.readline().decode("utf-8", errors="replace").strip()
                if line:
                    print(f"{C_MAGENTA}[UART ◄] {line}{C_RESET}")
                    # Publier le feedback de l'ESP32 sur MQTT
                    mqtt_client.publish(MQTT_TOPIC_FEEDBACK, line)
            else:
                time.sleep(0.05)
        except Exception as e:
            print(f"{C_RED}[ERREUR UART READER] {e}{C_RESET}")
            time.sleep(1)

# ── Callbacks MQTT ────────────────────────────────────────────
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"{C_CYAN}[MQTT] Connecté au broker {MQTT_BROKER}:{MQTT_PORT}{C_RESET}")
        client.subscribe(MQTT_TOPIC_ORDRES)
        print(f"{C_CYAN}[MQTT] Abonné au topic : {MQTT_TOPIC_ORDRES}{C_RESET}")
    else:
        print(f"{C_RED}[MQTT] Échec de connexion (code {rc}){C_RESET}")

def on_message(client, userdata, msg):
    """Callback appelé quand un ordre arrive sur mira/bridge/ordres."""
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        # Mode passthrough JSON direct vers ESP32 (NDJSON firmware)
        # Ex: {"t":"cmd","m":"walk","v":0.2} ou {"t":"srv","i":0,"a":90}
        if isinstance(payload, dict) and isinstance(payload.get("t"), str):
            frame = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            print(
                f"{C_BLUE}[BRIDGE] passthrough JSON → ESP32 : "
                f"{payload.get('t')}{C_RESET}"
            )
            send_uart(frame)
            return

        # Compat historique dashboard : {"action":"avance"}
        action = str(payload.get("action", "")).lower().strip()
        if action:
            uart_cmd = COMMAND_MAP.get(action)
            if uart_cmd:
                frame = f"<CMD:{uart_cmd}>\n"
                print(f"{C_BLUE}[BRIDGE] {action} → {uart_cmd}{C_RESET}")
                send_uart(frame)
            else:
                print(f"{C_YELLOW}[BRIDGE] Action inconnue : '{action}'{C_RESET}")
            return

        print(f"{C_YELLOW}[BRIDGE] Message sans champ exploitable (action|t) : {payload}{C_RESET}")

    except json.JSONDecodeError:
        print(f"{C_RED}[BRIDGE] JSON invalide : {msg.payload}{C_RESET}")
    except Exception as e:
        print(f"{C_RED}[BRIDGE] Erreur de traitement : {e}{C_RESET}")

def on_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"{C_YELLOW}[MQTT] Déconnexion inattendue (code {rc}). Reconnexion...{C_RESET}")

# ── Main ──────────────────────────────────────────────────────
def main():
    print(f"{C_CYAN}{'='*60}{C_RESET}")
    print(f"{C_CYAN}  M.I.R.A — Bridge MQTT → UART (ESP32){C_RESET}")
    print(f"{C_CYAN}{'='*60}{C_RESET}")
    print(f"{C_CYAN}  MQTT Broker  : {MQTT_BROKER}:{MQTT_PORT}{C_RESET}")
    print(f"{C_CYAN}  Topic ordres : {MQTT_TOPIC_ORDRES}{C_RESET}")
    print(f"{C_CYAN}  UART Port    : {UART_PORT} @ {UART_BAUD} baud{C_RESET}")
    print(f"{C_CYAN}{'='*60}{C_RESET}")

    # 1. Initialiser le port série
    serial_ok = init_serial()

    # 2. Initialiser MQTT
    print(f"{C_CYAN}[INIT] Connexion au broker MQTT...{C_RESET}")
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    except AttributeError:
        client = mqtt.Client()

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    # Reconnexion automatique
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    # Boucle de connexion avec retry
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            break
        except Exception as e:
            print(f"{C_RED}[MQTT] Impossible de se connecter : {e}. Retry dans 5s...{C_RESET}")
            time.sleep(5)

    # 3. Lancer le thread de lecture UART (feedback ESP32 → MQTT)
    if serial_ok:
        reader_thread = threading.Thread(target=uart_reader, args=(client,), daemon=True)
        reader_thread.start()
        print(f"{C_GREEN}[UART] Thread de lecture ESP32 démarré.{C_RESET}")

    # 4. Boucle MQTT
    print(f"{C_GREEN}>>> BRIDGE PRÊT. En attente d'ordres sur {MQTT_TOPIC_ORDRES}...{C_RESET}")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"{C_YELLOW}\n[BRIDGE] Arrêt demandé...{C_RESET}")
    finally:
        if serial_port and serial_port.is_open:
            serial_port.close()
            print(f"{C_CYAN}[UART] Port série fermé.{C_RESET}")
        client.loop_stop()
        client.disconnect()
        print(f"{C_GREEN}[BRIDGE] Arrêté proprement.{C_RESET}")

if __name__ == "__main__":
    main()
