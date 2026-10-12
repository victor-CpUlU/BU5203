"""Redaction of API keys from any text that is logged, stored or returned (Req 27.8, 27.9)."""
from __future__ import annotations

import logging

WINDOW = 8
MASK = "[REDACTED]"


def redact(text: str, secrets: list[str]) -> str:
    """Mask every span of `text` covered by any 8-character window of a secret."""
    if not text or not secrets:
        return text
    covered = [False] * len(text)
    for secret in secrets:
        if not secret:
            continue
        windows = {secret[i:i + WINDOW] for i in range(max(1, len(secret) - WINDOW + 1))} if len(secret) >= WINDOW else {secret}
        for w in windows:
            start = text.find(w)
            while start != -1:
                for k in range(start, start + len(w)):
                    covered[k] = True
                start = text.find(w, start + 1)
    if not any(covered):
        return text
    out, i = [], 0
    while i < len(text):
        if covered[i]:
            while i < len(text) and covered[i]:
                i += 1
            out.append(MASK)
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def redact_obj(obj, secrets: list[str]):
    """Recursively redact strings inside JSON-like objects."""
    if not secrets:
        return obj
    if isinstance(obj, str):
        return redact(obj, secrets)
    if isinstance(obj, list):
        return [redact_obj(v, secrets) for v in obj]
    if isinstance(obj, dict):
        return {k: redact_obj(v, secrets) for k, v in obj.items()}
    return obj


class RedactingFilter(logging.Filter):
    def __init__(self, secrets_provider):
        super().__init__()
        self._secrets = secrets_provider

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = self._secrets()
        if secrets:
            record.msg = redact(record.getMessage(), secrets)
            record.args = ()
        return True
