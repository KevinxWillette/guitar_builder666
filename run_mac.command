#!/bin/bash
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Install Python from python.org first."; read -p "press enter"; exit 1; }
python3 -m pip install --quiet pillow numpy opencv-python-headless
(sleep 2 && open http://localhost:8666) &
python3 -m guitar_mechanic app
