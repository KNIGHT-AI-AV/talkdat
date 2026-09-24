"""Bounded personal vocabulary hints, applied before local token selection.

The ONNX adapter is per call. Its immutable graph sessions are shared, but its
decoder method and vocabulary bias never replace those on the cached engine.
Unsupported engines retain their ordinary decode and the text dictionary.
"""
from __future__ import annotations

import copy
import re
from types import MethodType
from typing import Any

from .vocabulary import parse_terms

MAX_TERMS = 64
MAX_TERM_CHARS = 48
MAX_TOTAL_CHARS = 512
_PLAIN_TERM = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ '-])*$", re.UNICODE)


def clean_terms(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    result, seen, length = [], set(), 0
    for term in parse_terms(raw):
        text = " ".join(term.text.split())
        if not 2 <= len(text) <= MAX_TERM_CHARS or not _PLAIN_TERM.fullmatch(text):
            continue
        if len(text.split()) > 4 or text.casefold() in seen:
            continue
        if len(result) >= MAX_TERMS or length + len(text) > MAX_TOTAL_CHARS:
            break
        result.append(text)
        seen.add(text.casefold())
        length += len(text)
    return tuple(result)


def recognition_terms(config: dict) -> tuple[str, ...]:
    dictionary = config.get("dictionary", {}) if isinstance(config, dict) else {}
    if not isinstance(dictionary, dict) or dictionary.get("recognition_bias", True) is False:
        return ()
    # Personal entries only. The full product/industry dictionary is not an
    # acoustic prior and would drown the few names the person taught us.
    entries = []
    for key in ("words", "terms"):
        if isinstance(dictionary.get(key), (list, tuple)):
            entries.extend(dictionary[key])
    return clean_terms(entries)


class PhraseBias:
    """Prefer a taught spelling only while acoustic candidates are close.

    Match decoded prefixes instead of inventing a SentencePiece tokenizer.
    The same name can therefore be emitted through different valid subwords.
    Blank frames and duration predictions are never changed. Hints are a soft
    preference, not a forced transcript or a post-recognition substitution.
    """
    def __init__(self, vocab: dict[int, str], terms: tuple[str, ...], *, blank_id: int):
        self.vocab = vocab
        self.blank_id = blank_id
        pieces: dict[str, list[tuple[int, str]]] = {}
        for token_id, piece in vocab.items():
            if token_id == blank_id or not piece or "<" in piece:
                continue
            pieces.setdefault(piece[0], []).append((token_id, piece))
        candidates: dict[str, set[int]] = {}
        for term in clean_terms(terms):
            for variant in {term, term.lower(), term[:1].upper() + term[1:]}:
                phrase = " " + variant
                for index in range(len(phrase)):
                    suffix = phrase[index:]
                    for token_id, piece in pieces.get(suffix[0], []):
                        if suffix.startswith(piece) and piece.strip():
                            candidates.setdefault(phrase[:index], set()).add(token_id)
        self.roots = tuple(candidates.pop("", ()))
        # A space or "Co" is shared by ordinary prose. Increasing that prior
        # changed unrelated public speech in the calibration run. A stronger
        # continuation hint needs at least three already-emitted letters.
        self.prefixes = tuple(sorted(
            ((prefix, ids) for prefix, ids in candidates.items()
             if sum(character.isalpha() for character in prefix) >= 3),
            key=lambda item: len(item[0]), reverse=True,
        ))
        self.max_context = max((len(prefix) for prefix, _ in self.prefixes), default=0)

    def apply(self, logits: Any, tokens: list[int]) -> Any:
        if not len(logits) or int(logits.argmax()) == self.blank_id:
            return logits
        candidates = {token: 0.20 for token in self.roots}
        # At least one ordinary leading boundary remains even at sentence start.
        tail = " " + "".join(self.vocab.get(token, "") for token in tokens[-self.max_context:])
        for prefix, choices in self.prefixes:
            if tail.endswith(prefix):
                for token in choices:
                    candidates[token] = max(candidates.get(token, 0.0), 2.6)
        if not candidates:
            return logits
        output = logits.copy()
        for token, boost in candidates.items():
            if 0 <= token < len(output) and token != self.blank_id:
                output[token] += boost
        return output


def with_transducer_bias(engine: Any, terms: tuple[str, ...]) -> Any:
    terms = clean_terms(terms)
    asr = getattr(engine, "asr", None)
    if not terms or type(asr).__name__ not in {"NemoConformerTdt", "NemoConformerRnnt"}:
        return engine
    if not isinstance(getattr(asr, "_vocab", None), dict) or not callable(getattr(asr, "_decode", None)):
        return engine
    bias = PhraseBias(asr._vocab, terms, blank_id=asr._blank_idx)
    if not bias.roots and not bias.prefixes:
        return engine
    adapted = copy.copy(engine)
    adapted.asr = copy.copy(asr)
    original_decode = asr._decode

    def decode(_self: Any, previous_tokens: list[int], previous_state: Any, encoder: Any):
        logits, step, next_state = original_decode(previous_tokens, previous_state, encoder)
        return bias.apply(logits, previous_tokens), step, next_state

    adapted.asr._decode = MethodType(decode, adapted.asr)
    return adapted
