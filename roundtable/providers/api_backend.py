"""Call a provider's HTTP API as a specialist.

OpenAI and xAI both speak the same chat-completions shape, so one adapter
covers both — only the base URL, key and model differ, and all three are
config. That is also the escape hatch from vendor lock-in: any provider with an
OpenAI-compatible endpoint can be added to the config without new code.

This path is metered, so it is the fallback rather than the default: it exists
for when a CLI is not installed, when a specialist must run somewhere without
an interactive login, or when Killy wants a specific model the CLI will not
give him.

Written against ``urllib`` on purpose — the roundtable stays install-free.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from .base import BackendResult, SpecialistError, SpecialistTimeout, tail

#: Status codes worth a second try — transient congestion, not a bad request.
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class ApiBackend:
    """Chat-completions client for any OpenAI-compatible endpoint."""

    kind = "api"

    def __init__(self, name: str, label: str, spec: dict[str, Any], api_key: str):
        self.name = name
        self.label = label
        self.spec = spec
        self.api_key = api_key
        self.base_url = str(spec.get("base_url", "")).rstrip("/")
        if not self.base_url:
            raise ValueError(f"{name}: api.base_url is missing from the config")
        self.model = spec.get("model")
        if not self.model:
            raise ValueError(f"{name}: api.model is missing from the config")
        self.max_output_tokens = spec.get("max_output_tokens")
        # Providers disagree about what this field is called, and newer models
        # reject the older name outright, so it is config rather than a guess.
        self.max_tokens_field = spec.get("max_tokens_field", "max_tokens")
        self.extra_body: dict[str, Any] = dict(spec.get("extra_body") or {})
        self.retries = int(spec.get("retries", 1))

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _payload(self, system: str, brief: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": brief},
            ],
        }
        if self.max_output_tokens:
            body[self.max_tokens_field] = int(self.max_output_tokens)
        body.update(self.extra_body)
        return body

    def _post(self, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "killy-roundtable/0.1",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
        return json.loads(raw)

    def run(self, system: str, brief: str, timeout: float) -> BackendResult:
        body = self._payload(system, brief)
        attempts = max(1, self.retries + 1)
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                payload = self._post(body, timeout)
                break
            except urllib.error.HTTPError as exc:
                detail = tail(exc.read().decode("utf-8", "replace"))
                last_error = SpecialistError(
                    f"{self.label}'s API returned HTTP {exc.code}: {detail}"
                )
                if exc.code not in RETRY_STATUS or attempt == attempts - 1:
                    raise last_error from exc
            except socket.timeout as exc:
                raise SpecialistTimeout(
                    f"{self.label} did not answer within {timeout:.0f}s."
                ) from exc
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                if isinstance(reason, socket.timeout):
                    raise SpecialistTimeout(
                        f"{self.label} did not answer within {timeout:.0f}s."
                    ) from exc
                last_error = SpecialistError(
                    f"{self.label}'s API is unreachable: {reason}"
                )
                if attempt == attempts - 1:
                    raise last_error from exc
            except json.JSONDecodeError as exc:
                raise SpecialistError(
                    f"{self.label}'s API returned something that is not JSON."
                ) from exc
            # Back off before trying again: 1s, then 2s.
            time.sleep(2**attempt)
        else:  # pragma: no cover - the loop always breaks or raises
            raise last_error or SpecialistError(f"{self.label} could not be reached.")

        text = _extract_text(payload)
        if not text:
            finish = _first_finish_reason(payload)
            raise SpecialistError(
                f"{self.label}'s API returned an empty answer"
                + (f" (finish_reason={finish})." if finish else ".")
            )

        return BackendResult(
            text=text,
            model=payload.get("model") or str(self.model),
            usage=payload.get("usage"),
            debug={"endpoint": self.endpoint},
        )


def _extract_text(payload: dict[str, Any]) -> str:
    """Pull the assistant text out of a chat-completions response.

    Tolerant of the shapes providers actually return: plain string content, or
    the list-of-parts form some models use for reasoning output.
    """
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") in (None, "text", "output_text")
        ]
        return "\n".join(p for p in parts if p).strip()
    return ""


def _first_finish_reason(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices") or []
    if not choices:
        return None
    return (choices[0] or {}).get("finish_reason")
