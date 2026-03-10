#!/bin/bash
set -e

echo "Démarrage du conteneur Ollama..."
docker compose up -d

echo "Attente de l'initialisation d'Ollama (10s)..."
sleep 10

echo "Téléchargement du modèle qwen2.5:1.5b-instruct..."
docker compose exec ollama ollama pull qwen2.5:1.5b-instruct

echo "Création du modèle personnalisé basé sur le Modelfile..."
docker compose exec ollama ollama create mira -f /config/Modelfile

echo "Terminé ! Vous pouvez tester avec : docker compose exec ollama ollama run mira"
