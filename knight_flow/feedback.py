from __future__ import annotations

import json
import sys
import urllib.request
from urllib.parse import quote

from . import official_build
from .version import APP_VERSION


FEEDBACK_EMAIL = "Build@KnightAIAV.com"


def _encoded_size(text: str) -> int:
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8")) - 2


def feedback_log_excerpt(text: str, limit: int = 48_000) -> str:
    """Bound the log including JSON escaping, preferring complete newest lines."""
    text = text.strip()
    if _encoded_size(text) <= limit:
        return text
    lines = text.splitlines()
    if len(lines) > 1:
        kept = []
        for line in reversed(lines):
            candidate = "\n".join([line, *reversed(kept)])
            if _encoded_size(candidate) > limit:
                break
            kept.append(line)
        if kept:
            return "\n".join(reversed(kept))
    # Legacy plain-text logs can be a single long line. The UI previews this
    # exact excerpt; the typed message itself is never silently shortened.
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if _encoded_size(text[:middle]) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def validate_feedback_payload(payload: dict[str, str]) -> bytes:
    if type(payload) is not dict or type(payload.get("text")) is not str:
        raise ValueError("Write a few words before sending.")
    if len(payload["text"].encode("utf-16-le")) // 2 > 2000:
        raise ValueError("Keep the complete message within 2,000 characters, including the title or language name. Your draft is still here.")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise ValueError("This report is too large to send. Shorten the message or remove the formatting log; your draft is still here.")
    return encoded


def build_feedback_payload(
    *,
    kind: str = "feature",
    title: str = "",
    details: str = "",
    contact: str = "",
    language: str = "",
    context: str = "",
    logs: str = "",
) -> dict[str, str]:
    """The report as the backend stores it. Pure, so tests can pin it.

    Reply address is optional. App version and platform accompany the typed
    message (there is no plan to report: Talk DAT! is free); the caller supplies a log excerpt only with explicit consent.
    """
    pieces = []
    if language.strip():
        pieces.append(f"Requested language: {language.strip()}")
    if title.strip():
        pieces.append(title.strip())
    if details.strip():
        pieces.append(details.strip())
    text = "\n\n".join(pieces).strip()
    category = "language" if kind == "language" else "feature"
    payload = {
        "text": text,
        "context": (context.strip() or f"share-an-idea-{category}")[:64],
        "appVersion": APP_VERSION,
        "platform": "mac" if sys.platform == "darwin" else "windows",
        "reply": contact.strip()[:120],
    }
    # X-126: the formatting log rides along ONLY when the sender ticked the
    # consent box -- callers pass logs="" otherwise. It contains dictated
    # text, so it must never be attached implicitly (X-37 applies to every
    # path that is not this explicit one).
    if logs.strip():
        payload["logs"] = feedback_log_excerpt(logs)
    return payload


def submit_feedback(payload: dict[str, str], *, timeout: float = 8.0) -> bool:
    """POST the report to the commerce service. True only on a confirmed
    receipt. A failed request keeps the draft; email is a separate user action."""
    encoded = validate_feedback_payload(payload)
    if not payload["text"].strip():
        return False
    # A source build has no feedback inbox unless it is given one; False sends
    # the person to the mailto fallback, exactly as a network failure does.
    url = official_build.service_url(None, "/v1/feedback")
    if not url:
        return False
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8", "replace") or "{}")
            return type(body) is dict and body.get("received") is True
    except Exception:
        return False


def feedback_mailto(
    *,
    kind: str,
    title: str = "",
    details: str = "",
    contact: str = "",
    language: str = "",
) -> str:
    category = "Language request" if kind == "language" else "Talk DAT! feature idea"
    subject = f"{category}: {title.strip() or language.strip() or 'New idea'}"
    lines = [
        f"Request type: {category}",
        f"Talk DAT! version: {APP_VERSION}",
    ]
    if language.strip():
        lines.append(f"Requested language: {language.strip()}")
    if title.strip():
        lines.append(f"Title: {title.strip()}")
    if details.strip():
        lines.extend(["", "Details:", details.strip()])
    if contact.strip():
        lines.extend(["", f"Reply to: {contact.strip()}"])
    lines.extend(
        [
            "",
            "Privacy note: Talk DAT! did not attach transcripts, recordings, API keys, dictionary entries, or device logs.",
        ]
    )
    return f"mailto:{FEEDBACK_EMAIL}?subject={quote(subject)}&body={quote(chr(10).join(lines))}"
