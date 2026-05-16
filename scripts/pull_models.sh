#!/usr/bin/env bash
# Pull required Ollama models for the Second Brain stack.
set -euo pipefail

MODELS=("nomic-embed-text" "llama3.2")

for model in "${MODELS[@]}"; do
  echo "Pulling $model..."
  ollama pull "$model"
done

echo "All models ready."
