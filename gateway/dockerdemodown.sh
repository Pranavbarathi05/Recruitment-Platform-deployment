#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# The user requested these directories
DIRS=(
    "." # gateway (current dir)
    "api-1"
    "compiler-1"
    "frontend"
    "monitoring"
    "judge0"
)

echo "Stopping Docker Compose services..."

for dir in "${DIRS[@]}"; do
    echo "========================================"
    echo "Processing directory: $dir"
    echo "========================================"
    if [ -d "$dir" ]; then
        (cd "$dir" && docker compose down)
    else
        echo "Directory $dir not found. Skipping."
    fi
done

echo
echo "All requested Docker services stopped successfully."
echo "Running docker ps..."
docker ps
