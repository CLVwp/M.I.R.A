import os
import glob
import re
import subprocess
import paho.mqtt.client as mqtt
import requests
import json
import time

MQTT_BROKER = os.getenv("MQTT_HOST", "mosquitto")
TOPIC_LLM_REQ = "mira/llm/request"
TOPIC_TTS = "mira/ai/response"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434/api/generate")
JEECE_DIR = os.getenv("JEECE_DIR", "/app/jeece_data")

def search_jeece_context(query: str, directory_path: str) -> str:
    if not os.path.exists(directory_path):
        return ""

    all_lines = []
    txt_files = glob.glob(os.path.join(directory_path, "*.txt"))[:50]

    for file_path in txt_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                all_lines.extend([line.strip() for line in f if line.strip()])
        except OSError as e:
            pass

    stop_words = {"le","la","les","un","une","des","du","de","d","l","qu","que","qui","quoi","dont","et","ou","ni","mais","or","donc","car","a","à","au","aux","en","dans","par","pour","avec","sans","sous","sur","je","tu","il","elle","nous","vous","ils","elles","est","sont","suis","es","sommes","êtes","ont","as","ai","être","avoir","ce","cet","cette","ces","mon","ton","son","ma","ta","sa","mes","tes","ses","comment","combien","pourquoi","quand","quel","quelle","quels","quelles","peux","fait","fais","s","t","m","n","c","j"}
    query_words = re.findall(r"\b\w+\b", query.lower())
    keywords = [w for w in query_words if w not in stop_words and len(w) > 2]

    if not keywords:
        matched_lines = all_lines
    else:
        scored_lines = []
        for line in all_lines:
            line_lower = line.lower()
            score = sum(1 for k in keywords if re.search(r"\b" + re.escape(k) + r"\b", line_lower))
            scored_lines.append((score, line))

        scored_lines.sort(key=lambda x: x[0], reverse=True)
        matched_lines = [line for score, line in scored_lines if score > 0]

        if not matched_lines:
            matched_lines = all_lines

    merged_text = " ".join(matched_lines)
    words = merged_text.split()
    if len(words) > 300:
        merged_text = " ".join(words[:300])

    return merged_text

def text_to_speech(text: str):
    print(f"[TTS] Saying: {text}")
    try:
        tts_command = [
            "piper",
            "--model",
            "fr_FR-upmc-medium.onnx",
            "--output_file",
            "output.wav",
        ]
        subprocess.run(
            tts_command,
            input=text.encode("utf-8"),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["aplay", "output.wav"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Warning: Piper TTS playback failed: {e}")

class MiraLLM:
    def __init__(self):
        self.history = []
        self.client = mqtt.Client()
        self.client.on_message = self.on_message
        self.client.connect(MQTT_BROKER, 1883, 60)
        self.client.subscribe(TOPIC_LLM_REQ)

    def ask_ollama(self, user_prompt, context):
        prompt_system = (
            "Tu es M.I.R.A (Mobile Intelligent Robotic Assistant). Tu as été créé par Shaima Derouich, "
            "Clément Toledano, Clément Viellard, Enguerrand Droulers, Alex Huang et Alexandre Garreau de "
            "l'équipe G494 (ECE Paris / JEECE). Tu DOIS respecter impérativement ton contexte et les règles "
            "d'identité fournies ci-après. Réponds extrêmement brièvement.\n"
            f"CONTEXTE: {context}\n"
        )
        
        history_text = "\n".join(self.history[-4:])
        full_prompt = f"{history_text}\nUser: {user_prompt}\nMIRA:"

        try:
            print(f"[LLM] Prompting Ollama...")
            r = requests.post(OLLAMA_URL, json={
                "model": "mira",
                "system": prompt_system,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": 0.1}
            }, timeout=120)
            return r.json().get('response', "Erreur LLM")
        except:
            return "Cerveau hors-ligne. Connexion à Ollama impossible."

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode()
        try:
            req = json.loads(payload)
            prompt = req.get("prompt", "")
            direct_tts = req.get("direct_tts", False)
            
            if direct_tts:
                # Just speak the text directly (bypass Ollama)
                text_to_speech(prompt)
            else:
                context = search_jeece_context(prompt, JEECE_DIR)
                ans = self.ask_ollama(prompt, context)
                self.history.append(f"U: {prompt}")
                self.history.append(f"M: {ans}")
                
                # Speak answer
                text_to_speech(ans)
                
                # Optionally publish AI response back
                client.publish(TOPIC_TTS, ans)
                
        except json.JSONDecodeError:
            pass

    def run(self):
        print("MIRA LLM (Brain Brick) ONLINE")
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            print("Shutting down...")

if __name__ == "__main__":
    MiraLLM().run()
