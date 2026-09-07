#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# The user requested these directories
DIRS=(
    "." # gateway (current dir)
    "app-1"
    "compiler-1"
    "frontend"
    "monitoring"
    "judge0"
)

echo "Starting Docker Compose services..."

for dir in "${DIRS[@]}"; do
    echo "========================================"
    echo "Processing directory: $dir"
    echo "========================================"
    if [ -d "$dir" ]; then
        (cd "$dir" && docker compose up -d --build)
    else
        echo "Directory $dir not found. Skipping."
    fi
done

echo
echo "All requested Docker services started successfully."
echo "Running docker ps..."
docker ps
