#!/usr/bin/env python3
"""Launcher for the roundtable MCP server.

Claude needs one absolute path it can run from anywhere, which is all this file
is: it puts the repo on the import path and starts the server.

    claude mcp add killy-roundtable -- python3 /full/path/to/roundtable_server.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from roundtable.__main__ import main

if __name__ == "__main__":
    sys.exit(main(["serve"]))
