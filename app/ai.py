"""Optional AI features. They switch on only when ANTHROPIC_API_KEY is set.

The AI only READS photos. Decisions (safe/unsafe, counted/not counted) stay in rules.py.
"""
from __future__ import annotations

import base64
import json
import os
import re

MODEL = os.environ.get("JALSETU_AI_MODEL", "claude-haiku-4-5-20251001")
TIMEOUT_S = float(os.environ.get("JALSETU_AI_TIMEOUT", "25"))


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client():
    import anthropic  # imported lazily so the server runs without the package or key
    return anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=1)


def _ask_json(prompt: str, jpeg: bytes, max_tokens: int = 600) -> dict:
    msg = _client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(jpeg).decode()}},
            {"type": "text", "text": prompt},
        ]}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("AI reply had no JSON")
    return json.loads(m.group(0))


def verify_report_photo(jpeg: bytes, report_type_label: str, area: str, note: str) -> dict:
    """Returns {"cls": "good"|"bad", "text": "..."}; raises on failure."""
    v = _ask_json(
        f'You check photos attached to citizen water reports in Bengaluru. The report says: "{report_type_label}" '
        f'in {area}. Note: "{note[:300]}". Does the photo plausibly show this? '
        'Reply with only JSON: {"shows": "under 12 words", "matches": true or false}', jpeg, 200)
    shows = str(v.get("shows", ""))[:80]
    return {"cls": "good", "text": "AI: photo matches · " + shows} if v.get("matches") is True \
        else {"cls": "bad", "text": "AI: photo doesn't match · " + shows}


def read_lab_report(jpeg: bytes, keys: dict[str, str]) -> dict[str, float]:
    """Extract measured values from a lab report photo. Returns only numeric, non-negative values."""
    spec = "\n".join(f'"{k}": {label}' for k, label in keys.items())
    v = _ask_json(
        "Read this water test lab report. Extract the measured RESULT values (not the limits) for these "
        "parameters, converted to the units given. Use null if a parameter isn't in the report. For coliform "
        'or E. coli, "absent" or "nil" = 0 and "present" = 1. Reply with only a JSON object with these keys:\n' + spec,
        jpeg, 600)
    out = {}
    for k in keys:
        x = v.get(k)
        if isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0:
            out[k] = float(x)
    return out
