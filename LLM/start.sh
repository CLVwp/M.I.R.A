#!/bin/bash
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.pc.yml")

echo "Démarrage du conteneur Ollama (stack PC)..."
"${COMPOSE[@]}" up -d

echo "Attente de l'initialisation d'Ollama (10s)..."
sleep 10

echo "Téléchargement du modèle qwen2.5:1.5b-instruct..."
"${COMPOSE[@]}" exec ollama ollama pull qwen2.5:1.5b-instruct

echo "Création du modèle personnalisé basé sur le Modelfile..."
"${COMPOSE[@]}" exec ollama ollama create mira -f /config/Modelfile

echo "Terminé ! Test : ${COMPOSE[*]} exec ollama ollama run mira"
