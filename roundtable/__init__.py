"""Killy AI Roundtable — Claude leads the table, GPT and Grok are its specialists.

Killy talks to Claude. Claude decides which specialists a request needs, calls
them through this package, judges what comes back, and answers with one voice.
The specialists never talk to Killy directly.

Two properties are deliberate and load-bearing. It is **free**: specialists are
reached through the vendors' own CLIs, which Killy's chat subscriptions already
cover, and a lock in the config stops any paid API being called by accident. It
is **dependency-free**: stock Python, nothing to ``pip install``, so there is no
virtualenv to break six months from now.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
