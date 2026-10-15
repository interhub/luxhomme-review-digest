"""Batch classification with strict validation. Nothing the model says is trusted before it passes here."""
import json
import sys
import time

from . import store
from .config import SENTIMENTS, THEMES, prompt_text, prompt_version
from .llm import LLMError, complete, extract_json, model_name, provider_name

BATCH = 15
RETRIES = 2
LOW_CONFIDENCE = 0.6


def validate_batch(parsed: dict, sent_ids: list[str]) -> dict[str, dict]:
    """Return {id: result} or raise ValueError describing the first problem."""
    items = parsed.get("results")
    if not isinstance(items, list):
        raise ValueError("missing results list")
    out = {}
    for item in items:
        rid = item.get("id")
        if rid not in sent_ids:
            raise ValueError(f"unknown id {rid!r}")
        if rid in out:
            raise ValueError(f"duplicate id {rid!r}")
        themes = item.get("themes")
        if not isinstance(themes, list) or not themes:
            raise ValueError(f"{rid}: no themes")
        seen = set()
        for t in themes:
            if t.get("theme") not in THEMES:
                raise ValueError(f"{rid}: unknown theme {t.get('theme')!r}")
            if t.get("sentiment") not in SENTIMENTS:
                raise ValueError(f"{rid}: bad sentiment {t.get('sentiment')!r}")
            if t["theme"] in seen:
                raise ValueError(f"{rid}: repeated theme {t['theme']}")
            seen.add(t["theme"])
        conf = item.get("confidence")
        if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
            raise ValueError(f"{rid}: bad confidence {conf!r}")
        out[rid] = {"themes": [{"theme": t["theme"], "sentiment": t["sentiment"]} for t in themes],
                    "other_label": item.get("other_label"), "confidence": float(conf)}
    missing = [i for i in sent_ids if i not in out]
    if missing:
        raise ValueError(f"missing ids {missing}")
    return out


def flags_for(review: dict, result: dict) -> list[str]:
    """Code-side checks that send a review to a human instead of trusting the label."""
    flags = []
    sentiments = {t["sentiment"] for t in result["themes"]}
    if review["rating"] == 5 and sentiments == {"neg"}:
        flags.append("rating_mismatch")
    if review["rating"] <= 2 and sentiments == {"pos"}:
        flags.append("rating_mismatch")
    if result["confidence"] < LOW_CONFIDENCE:
        flags.append("low_confidence")
    if any(t["theme"] == "other" for t in result["themes"]):
        flags.append("other_theme")
    return flags


def build_user(reviews: list[dict]) -> str:
    return json.dumps({"reviews": [{"id": r["id"], "sku": r["sku"], "rating": r["rating"], "text": r["text"]}
                                   for r in reviews]}, ensure_ascii=False)


def classify(reviews: list[dict], provider: str | None = None) -> dict[str, dict]:
    """Classify one batch, retrying on invalid output. Raises LLMError after the last attempt."""
    system = prompt_text()
    sent = [r["id"] for r in reviews]
    user = build_user(reviews)
    last = ""
    for attempt in range(1, RETRIES + 2):
        try:
            return validate_batch(extract_json(complete(system, user, provider)), sent)
        except (ValueError, KeyError, AttributeError, TypeError, LLMError) as e:
            last = str(e)
            print(f"  batch rejected (attempt {attempt}): {last}", file=sys.stderr)
            if isinstance(e, LLMError):
                time.sleep(2 * attempt)  # network or rate limit: back off before the next try
    raise LLMError(f"batch failed validation after {RETRIES + 1} attempts: {last}")


def run(conn, force: bool = False, provider: str | None = None) -> dict:
    todo = store.pending(conn, force)
    provider = provider or provider_name()
    model, version = model_name(provider), prompt_version()
    done = failed = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            results = classify(batch, provider)
        except LLMError as e:
            failed += len(batch)
            print(f"  skipped {len(batch)} reviews, they stay pending: {e}", file=sys.stderr)
            continue
        for r in batch:
            store.save_analysis(conn, r["id"], results[r["id"]], flags_for(r, results[r["id"]]), model, version)
        done += len(batch)
        print(f"  analyzed {done}/{len(todo)}", file=sys.stderr)
    return {"analyzed": done, "failed": failed, "model": model, "prompt_version": version}
