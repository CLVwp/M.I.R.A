import paho.mqtt.client as mqtt
import requests
import json
import time

MQTT_BROKER = "localhost"
TOPIC_STT = "mira/stt/output"
TOPIC_VISION = "mira/vision/detections"
TOPIC_TTS = "mira/ai/response"
TOPIC_ROBOT = "mira/robot/control"
OLLAMA_URL = "http://localhost:11434/api/generate"

COMMANDS = {
    "avance": "MOVE_FORWARD",
    "recule": "MOVE_BACKWARD",
    "stop": "STOP",
    "assis": "SIT_DOWN",
    "debout": "STAND_UP"
}

class MiraBrain:
    def __init__(self):
        self.history = []
        self.last_threat_time = 0
        self.threat_cooldown = 5
        self.client = mqtt.Client()
        self.client.on_message = self.on_message
        self.client.connect(MQTT_BROKER, 1883, 60)
        self.client.subscribe([(TOPIC_STT, 0), (TOPIC_VISION, 0)])

    def ask_ollama(self, prompt):
        context = "\n".join(self.history[-4:])
        full_prompt = f"Tu es M.I.R.A. Réponds brièvement.\nContext:\n{context}\nUser: {prompt}\nMIRA:"
        try:
            r = requests.post(OLLAMA_URL, json={
                "model": "ministral:3b",
                "prompt": full_prompt,
                "stream": False
            }, timeout=10)
            return r.json().get('response', "Erreur LLM")
        except:
            return "Cerveau hors-ligne."

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode()
        
        if msg.topic == TOPIC_VISION:
            data = json.loads(payload)
            if data.get("status") == "CRITICAL":
                current_time = time.time()
                if current_time - self.last_threat_time > self.threat_cooldown:
                    item = data.get("item", "danger")
                    print(f"ALERTE : {item}")
                    self.last_threat_time = current_time
                    client.publish(TOPIC_TTS, f"Alerte ! Je détecte un {item}.")
                    client.publish(TOPIC_ROBOT, "ACTION_SAFE_RETREAT")

        elif msg.topic == TOPIC_STT:
            text = payload.lower().strip()
            if len(text) < 2: return
            
            found_cmd = False
            for cmd, action in COMMANDS.items():
                if cmd in text:
                    client.publish(TOPIC_ROBOT, action)
                    client.publish(TOPIC_TTS, f"Je vais {cmd}.")
                    found_cmd = True
                    break
            
            if not found_cmd:
                ans = self.ask_ollama(text)
                self.history.append(f"U: {text}")
                self.history.append(f"M: {ans}")
                client.publish(TOPIC_TTS, ans)

    def run(self):
        print("MIRA BRIDGE ONLINE")
        self.client.loop_forever()

if __name__ == "__main__":
    MiraBrain().run()