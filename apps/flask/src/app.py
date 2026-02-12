from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/generate")
def generate():
    data = request.get_json(force=True)
    prompt = data.get("prompt", "Diga oi.")
    model = data.get("model", "llama3.2:3b")

    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    r.raise_for_status()
    return jsonify(r.json())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
