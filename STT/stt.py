import os
import sys
import json
import queue
import struct
import threading
import time
import numpy as np
import requests
import sounddevice as sd
import paho.mqtt.client as mqtt
from vosk import Model, KaldiRecognizer

VOSK_RATE = 16000
WAKE_WORDS = ["mira", "miro"]
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://100.68.211.25:11434/api/generate")
MODEL_NAME = os.getenv("OLLAMA_MODEL", "mira")
MODEL_PATH = os.getenv("VOSK_MODEL", "/app/model")
NOISE_THRESHOLD = int(os.getenv("NOISE_THRESHOLD", "300"))
MQTT_BROKER = os.getenv("MQTT_BROKER", "mira-mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
# Identifiant robot pour le dashboard (topic mira/robots/{id}/listening)
ROBOT_ID = os.getenv("ROBOT_ID", "mira-robot")

derniere_vision = "Rien à signaler"
last_vision_time = 0.0
mqtt_client = None

MOTOR_COMMANDS = {
    "avance", "avancer", "recule", "reculer", "recul",
    "autopilot", "autopilote", "stop", "stoppe", "arrête", 
    "arreter", "gauche", "droite", "position",
}

C_RESET, C_GREEN, C_CYAN, C_YELLOW, C_RED, C_BLUE = (
    "\033[0m", "\033[1;32m", "\033[0;36m", "\033[1;33m", "\033[1;31m", "\033[1;34m"
)

def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    print(f"{C_CYAN}[MQTT] Connecté code {rc}.{C_RESET}")
    client.subscribe("mira/vision/output")

def on_mqtt_message(client, userdata, msg):
    global derniere_vision, last_vision_time
    derniere_vision = msg.payload.decode("utf-8")
    last_vision_time = time.time()

audio_queue = queue.Queue()

def audio_callback(indata, frames, time_info, status):
    if status: print(f"{C_YELLOW}[AUDIO] {status}{C_RESET}", file=sys.stderr)
    audio_queue.put(bytes(indata))

def compute_rms(data):
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    return np.sqrt(np.mean(samples ** 2)) if len(samples) > 0 else 0

def noise_gate(data, threshold):
    rms = compute_rms(data)
    if rms < threshold: return b'\x00' * len(data), rms, True
    return data, rms, False

def downsample(data, from_rate, to_rate):
    if from_rate == to_rate: return data
    samples = np.frombuffer(data, dtype=np.int16)
    ratio = from_rate // to_rate
    return samples[::ratio].tobytes()

def detect_motor_command(text):
    words = text.lower().split()
    for word in words:
        if word in MOTOR_COMMANDS: return word
    return None

def ask_ollama(prompt):
    try:
        print(f"{C_CYAN}[LLM] Envoi...{C_RESET}")
        r = requests.post(OLLAMA_URL, json={
            "model": MODEL_NAME, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.1}
        }, timeout=120)
        return r.json().get("response", "...")
    except Exception as e: return f"Erreur: {e}"

def publish_listening(text: str):
    """Remonte la transcription Vosk vers le dashboard (MQTT)."""
    if not mqtt_client:
        return
    topic = f"mira/robots/{ROBOT_ID}/listening"
    payload = json.dumps({
        "text": text,
        "ts": time.time(),
        "source": "vosk",
    })
    try:
        mqtt_client.publish(topic, payload, qos=0)
    except Exception as e:
        print(f"{C_RED}[MQTT] publish listening: {e}{C_RESET}")

def process_text(text):
    text_lower = text.lower().strip()
    
    found_wake = next((w for w in WAKE_WORDS if w in text_lower), None)
    if not found_wake: return

    idx = text_lower.index(found_wake) + len(found_wake)
    after_wake = text_lower[idx:].strip()

    if not after_wake:
        print(f"{C_YELLOW}[WAKE] {found_wake} détecté.{C_RESET}")
        return

    print(f"{C_GREEN}[WAKE] Commande : \"{after_wake}\"{C_RESET}")

    motor_cmd = detect_motor_command(after_wake)
    if motor_cmd:
        if mqtt_client:
            mqtt_client.publish("mira/bridge/ordres", json.dumps({"action": motor_cmd}))
        return

    threading.Thread(target=_ask_and_print, args=(after_wake,), daemon=True).start()

def _ask_and_print(prompt):
    global derniere_vision, last_vision_time
    
    if time.time() - last_vision_time <= 20:
        vision_contexte = f"En ce moment, tu vois : {derniere_vision}."
    else:
        vision_contexte = "Tu ne vois rien de particulier ou la caméra est obstruée."

    full_prompt = (
        f"CONTEXTE VISUEL : {vision_contexte}\n"
        f"COMMANDE VOCALE : {prompt}\n\n"
        f"CONSIGNE : En tant que robot M.I.R.A, réponds à la commande vocale "
        f"en utilisant les informations du contexte visuel si nécessaire. "
        f"Sois bref et direct."
    )
    
    response = ask_ollama(full_prompt)
    print(f"{C_GREEN}[MIRA] {response}{C_RESET}")
    if mqtt_client:
        mqtt_client.publish("mira/stt/reponse", response)
        mqtt_client.publish("mira/tts/say", response)

def main():
    global mqtt_client
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except: pass

    model = Model(MODEL_PATH)
    recognizer = KaldiRecognizer(model, VOSK_RATE)
    device_id = sd.default.device[0]
    device_rate = int(sd.query_devices(device_id)['default_samplerate'])

    print(f"{C_GREEN}>>> M.I.R.A PRÊTE ({WAKE_WORDS}){C_RESET}")

    with sd.RawInputStream(samplerate=device_rate, blocksize=32000, device=device_id,
                           dtype="int16", channels=1, callback=audio_callback):
        while True:
            data = audio_queue.get()
            data = downsample(data, device_rate, VOSK_RATE)
            data, _, _ = noise_gate(data, NOISE_THRESHOLD)
            if recognizer.AcceptWaveform(data):
                res = json.loads(recognizer.Result())
                text = res.get("text", "")
                if text:
                    print(f"{C_CYAN}[STT] \"{text}\"{C_RESET}")
                    publish_listening(text)
                    process_text(text)

if __name__ == "__main__":
    main()