import requests

ollama_url = "http://localhost:11434/api/generate"
payload = {
    "model": "mistral",
    "system": "Tu es M.I.R.A.",
    "prompt": "MIRA, qui es tu ?",
    "stream": False,
}

try:
    print("Sending request to Ollama...")
    response = requests.post(ollama_url, json=payload, timeout=15)
    print("Status:", response.status_code)
    print("Response:", response.text[:200])
except Exception as e:
    print(f"Error: {e}")
