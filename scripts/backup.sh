#!/usr/bin/env bash
# backup.sh — snapshot Qdrant + archive vault and index state
#
# Usage:
#   ./scripts/backup.sh                     # default: backup/ in project root
#   BACKUP_DIR=/mnt/backups ./scripts/backup.sh
#
# What it backs up:
#   1. Qdrant snapshot  — binary snapshot of all collections via REST API
#   2. Vault archive    — tar.gz of the Obsidian markdown files
#   3. Index state      — JSON file tracking note hashes for incremental sync
#
# Requirements:
#   - curl, tar (standard on Linux/macOS)
#   - Qdrant must be running and reachable at QDRANT_URL
#   - Set VAULT_PATH and INDEX_STATE_PATH to match your .env values

set -euo pipefail

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-second_brain}"
VAULT_PATH="${VAULT_PATH:-./vault}"
INDEX_STATE_PATH="${INDEX_STATE_PATH:-./backend/data/index_state.json}"
BACKUP_DIR="${BACKUP_DIR:-./backup}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DEST="${BACKUP_DIR}/${TIMESTAMP}"

mkdir -p "${DEST}"

echo "==> Backup started: ${DEST}"

# ── 1. Qdrant snapshot ────────────────────────────────────────────────────────
echo "==> Creating Qdrant snapshot for collection: ${QDRANT_COLLECTION}"
SNAPSHOT_RESPONSE=$(curl -sf -X POST \
    "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/snapshots")

SNAPSHOT_NAME=$(echo "${SNAPSHOT_RESPONSE}" | grep -o '"name":"[^"]*"' | cut -d'"' -f4)

if [ -z "${SNAPSHOT_NAME}" ]; then
    echo "ERROR: Failed to create Qdrant snapshot. Response: ${SNAPSHOT_RESPONSE}"
    exit 1
fi

echo "    Snapshot created: ${SNAPSHOT_NAME}"
echo "    Downloading..."

curl -sf -o "${DEST}/qdrant_${QDRANT_COLLECTION}.snapshot" \
    "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/snapshots/${SNAPSHOT_NAME}"

# Clean up the snapshot from Qdrant storage (optional — saves disk space on server)
curl -sf -X DELETE \
    "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/snapshots/${SNAPSHOT_NAME}" \
    > /dev/null

echo "    Qdrant snapshot saved: qdrant_${QDRANT_COLLECTION}.snapshot"

# ── 2. Vault archive ──────────────────────────────────────────────────────────
if [ -d "${VAULT_PATH}" ]; then
    echo "==> Archiving vault: ${VAULT_PATH}"
    tar -czf "${DEST}/vault.tar.gz" -C "$(dirname "${VAULT_PATH}")" \
        "$(basename "${VAULT_PATH}")"
    echo "    Vault archived: vault.tar.gz"
else
    echo "WARN: Vault path not found, skipping: ${VAULT_PATH}"
fi

# ── 3. Index state ────────────────────────────────────────────────────────────
if [ -f "${INDEX_STATE_PATH}" ]; then
    echo "==> Copying index state: ${INDEX_STATE_PATH}"
    cp "${INDEX_STATE_PATH}" "${DEST}/index_state.json"
    echo "    Index state copied: index_state.json"
else
    echo "WARN: Index state file not found, skipping: ${INDEX_STATE_PATH}"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "==> Backup complete: ${DEST}"
ls -lh "${DEST}"
echo ""
echo "To restore Qdrant snapshot:"
echo "  curl -X POST '${QDRANT_URL}/collections/${QDRANT_COLLECTION}/snapshots/upload' \\"
echo "    -H 'Content-Type: multipart/form-data' \\"
echo "    -F 'snapshot=@${DEST}/qdrant_${QDRANT_COLLECTION}.snapshot'"
