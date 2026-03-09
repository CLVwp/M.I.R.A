"""
M.I.R.A Orchestrator module.
Handles STT input, intent routing, hardware communication, and LLM context injection.
"""

import os
import re
import glob
import subprocess
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import serial
import requests

app = FastAPI(title="M.I.R.A Orchestrator")

# UART Configuration
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
BAUD_RATE = 115200

try:
    ESP32_SER = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    print(f"Connected to ESP32 on {SERIAL_PORT}")
except serial.SerialException as e:
    print(f"Warning: Serial port {SERIAL_PORT} not available. {e}")
    ESP32_SER = None


class STTInput(BaseModel):
    """
    Model representing the input data from the STT module.
    """

    text: str


def detect_intent(text: str) -> str | None:
    """
    Compare received text to a list of commands.
    Returns the command if matched, else None.
    """
    commands = ["AVANCE", "RECULE", "STOP", "DROITE", "GAUCHE", "SCANNE", "AUTOPILOTE"]
    text_lower = text.lower()
    for cmd in commands:
        if re.search(r"\b" + re.escape(cmd.lower()) + r"\b", text_lower):
            return cmd
    return None


def send_to_esp32(command: str):
    """
    Sends a plain text command to the ESP32 via UART.
    """
    if ESP32_SER and ESP32_SER.is_open:
        try:
            ESP32_SER.write(f"{command}\n".encode("utf-8"))
            print(f"Sent to ESP32: {command}")
        except serial.SerialException as e:
            print(f"Error sending to UART: {e}")
    else:
        print(f"[Mock] Sent to ESP32: {command}")


def search_jeece_context(query: str, directory_path: str) -> str:
    """
    Scans up to 50 .txt files in `directory_path` at flat level.
    Extracts lines containing query keywords (ignoring stop words).
    Returns a merged text block limited to 300 words (~400 tokens).
    """
    if not os.path.exists(directory_path):
        return ""

    all_lines = []
    txt_files = glob.glob(os.path.join(directory_path, "*.txt"))[:50]

    for file_path in txt_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                all_lines.extend([line.strip() for line in f if line.strip()])
        except OSError as e:
            print(f"Error reading file {file_path}: {e}")

    # Stop words in French
    stop_words = {
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "du",
        "de",
        "d",
        "l",
        "qu",
        "que",
        "qui",
        "quoi",
        "dont",
        "et",
        "ou",
        "ni",
        "mais",
        "or",
        "donc",
        "car",
        "a",
        "à",
        "au",
        "aux",
        "en",
        "dans",
        "par",
        "pour",
        "avec",
        "sans",
        "sous",
        "sur",
        "je",
        "tu",
        "il",
        "elle",
        "nous",
        "vous",
        "ils",
        "elles",
        "est",
        "sont",
        "suis",
        "es",
        "sommes",
        "êtes",
        "ont",
        "as",
        "ai",
        "être",
        "avoir",
        "ce",
        "cet",
        "cette",
        "ces",
        "mon",
        "ton",
        "son",
        "ma",
        "ta",
        "sa",
        "mes",
        "tes",
        "ses",
        "comment",
        "combien",
        "pourquoi",
        "quand",
        "quel",
        "quelle",
        "quels",
        "quelles",
        "peux",
        "fait",
        "fais",
        "s",
        "t",
        "m",
        "n",
        "c",
        "j",
    }

    # Extract words from query (only word characters)
    query_words = re.findall(r"\b\w+\b", query.lower())
    keywords = [w for w in query_words if w not in stop_words and len(w) > 2]

    if not keywords:
        # Fallback: if no meaningful keywords (e.g. "Qui es tu ?"), return everything
        matched_lines = all_lines
    else:
        # Score each line based on whole-word matches
        scored_lines = []
        for line in all_lines:
            line_lower = line.lower()
            score = sum(
                1
                for k in keywords
                if re.search(r"\b" + re.escape(k) + r"\b", line_lower)
            )
            scored_lines.append((score, line))

        # Sort by highest score first
        scored_lines.sort(key=lambda x: x[0], reverse=True)

        # Only keep lines with at least 1 match
        matched_lines = [line for score, line in scored_lines if score > 0]

        # If no line matched any keyword, fallback to providing everything
        if not matched_lines:
            matched_lines = all_lines

    # Merge and limit to 300 words
    merged_text = " ".join(matched_lines)
    words = merged_text.split()
    if len(words) > 300:
        merged_text = " ".join(words[:300])

    return merged_text


@app.post("/process")
def process_stt_input(data: STTInput):
    """
    Process STT input, route intents to hardware or LLM based on commands.
    """
    text = data.text
    print(f"Received STT text: {text}")

    # 2. Routeur d'Intention
    command = detect_intent(text)

    if command:
        # 3. Communication Matérielle
        send_to_esp32(command)
        return {"status": "success", "action": "motor_command", "command": command}

    # 4. Le Moteur de Recherche "Grep Brut" (RAG)
    jeece_directory = os.getenv("JEECE_DIR", "./jeece_data")
    context = search_jeece_context(text, jeece_directory)

    # 5. Injection de Contexte et Appel LLM
    prompt_system = (
        "Tu es M.I.R.A (Mobile Intelligent Robotic Assistant). Tu as été créé par Shaima Derouich, "
        "Clément Toledano, Clément Viellard, Enguerrand Droulers, Alex Huang et Alexandre Garreau de "
        "l'équipe G494 (ECE Paris / JEECE). Tu DOIS respecter impérativement ton contexte et les règles "
        "d'identité fournies ci-après.\n"
        f"CONTEXTE: {context}\n"
    )
    prompt_user = text

    # Usually locally running Ollama is on 11434
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    ollama_payload = {
        "model": "mira",
        "system": prompt_system,
        "prompt": prompt_user,
        "stream": False,
        "options": {"temperature": 0.1},  # On rend le modèle très strict
    }

    try:
        response = requests.post(ollama_url, json=ollama_payload, timeout=120)
        response.raise_for_status()
        llm_reply = response.json().get("response", "")

        # 6. Text-To-Speech (TTS) avec Piper
        # Lancer piper en sous-processus pour générer l'audio
        # Requires a trained model, e.g., fr_FR-upmc-medium.onnx
        try:
            tts_command = [
                "piper",
                "--model",
                "fr_FR-upmc-medium.onnx",
                "--output_file",
                "output.wav",
            ]

            # Écrire le texte sur l'entrée standard (stdin) de Piper
            subprocess.run(
                tts_command,
                input=llm_reply.encode("utf-8"),
                check=True,
                stdout=subprocess.DEVNULL,  # Masquer les logs verbeux de piper
                stderr=subprocess.DEVNULL,
            )
            print("Audio output.wav generated successfully via Piper.")

            # (Optionnel) Ici, on pourrait lancer une commande 'aplay output.wav'
            # pour que le robot parle physiquement.

        except FileNotFoundError:
            print("Warning: Piper TTS is not installed or not found in PATH.")
        except subprocess.CalledProcessError as e:
            print(f"Warning: Piper TTS generation failed: {e}")

        return {
            "status": "success",
            "action": "llm_response",
            "response": llm_reply,
            "audio_generated": True,
        }
    except requests.RequestException as e:
        print(f"Error calling Ollama: {e}")
        raise HTTPException(
            status_code=500, detail="Error communicating with LLM"
        ) from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)
