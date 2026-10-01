#!/usr/bin/env bash
# Скачивание GGUF-модели для LLM Engine (Shade Core).
# Модель НЕ хранится в git (core/models/ в .gitignore).
#
# Использование:
#   ./scripts/download_model.sh                 # модель по умолчанию (TinyLlama, ~670 MB)
#   MODEL=qwen ./scripts/download_model.sh      # Qwen 2.5 1.5B — лучше для русского (~1 GB)
set -euo pipefail

DEST_DIR="$(cd "$(dirname "$0")/.." && pwd)/core/models"
mkdir -p "$DEST_DIR"

case "${MODEL:-tinyllama}" in
tinyllama)
  URL="https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
  FILE="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
  ;;
qwen)
  URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
  FILE="qwen2.5-1.5b-instruct-q4_k_m.gguf"
  ;;
*)
  echo "Неизвестная модель: $MODEL (доступно: tinyllama, qwen)" >&2
  exit 1
  ;;
esac

echo "Скачивание $FILE -> $DEST_DIR/"
curl -fL --progress-bar -C - -o "$DEST_DIR/$FILE" "$URL"
echo "Готово: $DEST_DIR/$FILE"
echo "Проверь, что LLM_MODEL_PATH в core/.env указывает на этот файл."
