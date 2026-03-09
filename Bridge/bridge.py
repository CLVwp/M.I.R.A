import os
import re
import json
import time
import serial
import paho.mqtt.client as mqtt
import requests

MQTT_BROKER = os.getenv("MQTT_HOST", "mosquitto")
TOPIC_STT = "mira/stt/output"
TOPIC_VISION = "mira/vision/detections"
TOPIC_TTS = "mira/ai/response"
TOPIC_ROBOT = "mira/robot/control"
TOPIC_LLM_REQ = "mira/llm/request"

SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
BAUD_RATE = 115200

COMMANDS = {
    "avance": "MOVE_FORWARD",
    "recule": "MOVE_BACKWARD",
    "stop": "STOP",
    "droite": "MOVE_RIGHT",
    "gauche": "MOVE_LEFT",
    "scanne": "SCAN_AREA",
    "autopilote": "AUTOPILOT_ON",
    "assis": "SIT_DOWN",
    "debout": "STAND_UP"
}

try:
    ESP32_SER = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    print(f"Connected to ESP32 on {SERIAL_PORT}")
except serial.SerialException as e:
    print(f"Warning: Serial port {SERIAL_PORT} not available. {e}")
    ESP32_SER = None

def detect_intent(text: str) -> str | None:
    text_lower = text.lower()
    for cmd, action in COMMANDS.items():
        if re.search(r"\b" + re.escape(cmd) + r"\b", text_lower):
            return action, cmd
    return None, None

def send_to_esp32(command: str):
    if ESP32_SER and ESP32_SER.is_open:
        try:
            ESP32_SER.write(f"{command}\n".encode("utf-8"))
            print(f"Sent to ESP32: {command}")
        except serial.SerialException as e:
            print(f"Error sending to UART: {e}")
    else:
        print(f"[Mock] Sent to ESP32: {command}")

class MiraBridge:
    def __init__(self):
        self.last_threat_time = 0
        self.threat_cooldown = 5
        self.client = mqtt.Client()
        self.client.on_message = self.on_message
        self.client.connect(MQTT_BROKER, 1883, 60)
        self.client.subscribe([(TOPIC_STT, 0), (TOPIC_VISION, 0), (TOPIC_ROBOT, 0)])

    def ask_llm(self, text):
        # Publish request to the LLM brick
        print(f"[Bridge] Requesting LLM for: {text}")
        self.client.publish(TOPIC_LLM_REQ, json.dumps({"prompt": text}))

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode()
        
        if msg.topic == TOPIC_VISION:
            try:
                data = json.loads(payload)
                if data.get("status") == "CRITICAL":
                    current_time = time.time()
                    if current_time - self.last_threat_time > self.threat_cooldown:
                        item = data.get("item", "danger")
                        self.last_threat_time = current_time
                        
                        warning_msg = f"Alerte ! Je détecte un {item}."
                        print(f"ALERTE : {item}")
                        client.publish(TOPIC_LLM_REQ, json.dumps({"prompt": warning_msg, "direct_tts": True}))
                        send_to_esp32("ACTION_SAFE_RETREAT")
            except json.JSONDecodeError:
                pass

        elif msg.topic == TOPIC_STT:
            text = payload.strip()
            if len(text) < 2: return
            print(f"[Bridge] Heard via STT: {text}")
            
            action, cmd_word = detect_intent(text)
            
            if action:
                send_to_esp32(action)
                client.publish(TOPIC_LLM_REQ, json.dumps({"prompt": f"Je vais {cmd_word}.", "direct_tts": True}))
            else:
                self.ask_llm(text)
                
        elif msg.topic == TOPIC_ROBOT:
            send_to_esp32(payload.strip())

    def run(self):
        print("MIRA BRIDGE (Orchestrator Brick) ONLINE")
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("Shutting down...")

if __name__ == "__main__":
    MiraBridge().run()