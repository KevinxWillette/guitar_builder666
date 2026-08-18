#!/bin/bash
# Double-click this to connect GPT and Grok to Claude as specialists.
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Install Python from python.org first."; read -p "press enter"; exit 1; }
python3 -m roundtable setup
echo
read -p "press enter to close"
