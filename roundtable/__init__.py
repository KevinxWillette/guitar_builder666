"""Killy AI Roundtable — Claude leads the table, GPT and Grok are its specialists.

Killy talks to Claude. Claude decides which specialists a request needs, calls
them through this package, judges what comes back, and answers with one voice.
The specialists never talk to Killy directly.

The package is deliberately dependency-free: it runs on the same stock Python
that already drives the guitar mechanic, so there is nothing to ``pip install``
before the roundtable works.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
