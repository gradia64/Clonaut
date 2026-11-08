#!/usr/bin/env bash
# Avvia Clonaut (le opzioni vengono passate a main.py, es.: --config /percorso/rclone.conf)
cd "$(dirname "$0")"
exec python3 main.py "$@"
