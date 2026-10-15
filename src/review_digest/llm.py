"""LLM providers. Each takes (system, user) and returns the raw model text."""
import hashlib
import json
import re
import urllib.request

from .config import ROOT, env

DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "replay": "claude-sonnet-5-5 (recorded)", "mock": "keyword-rules"}
RECORDED_DIR = ROOT / "data" / "llm_responses"


class LLMError(RuntimeError):
    pass


def model_name(provider: str) -> str:
    return env("REVIEW_LLM_MODEL") or DEFAULT_MODELS[provider]


def provider_name() -> str:
    # no silent fallback: a digest built by keyword rules must never pass for an LLM one
    return env("REVIEW_LLM_PROVIDER", "anthropic")


def request_key(system: str, user: str) -> str:
    return hashlib.sha1(f"{system}\n{user}".encode("utf-8")).hexdigest()[:12]


def complete(system: str, user: str, provider: str | None = None) -> str:
    provider = provider or provider_name()
    if provider == "anthropic":
        raw = _anthropic(system, user, model_name(provider))
        if env("REVIEW_LLM_RECORD"):
            RECORDED_DIR.mkdir(parents=True, exist_ok=True)
            (RECORDED_DIR / f"{request_key(system, user)}.txt").write_text(raw, encoding="utf-8")
        return raw
    if provider == "replay":
        path = RECORDED_DIR / f"{request_key(system, user)}.txt"
        if not path.exists():
            raise LLMError(f"no recorded response for this batch ({path.name}); record one with "
                           "REVIEW_LLM_RECORD=1 and a live provider")
        return path.read_text(encoding="utf-8")
    if provider == "mock":
        from .mock_llm import classify_batch
        return classify_batch(user)
    raise LLMError(f"unknown provider {provider!r}, use anthropic | replay | mock")


def _anthropic(system: str, user: str, model: str) -> str:
    key = env("ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set (or use REVIEW_LLM_PROVIDER=replay for the recorded demo)")
    body = json.dumps({"model": model, "max_tokens": 4096, "temperature": 0, "system": system,
                       "messages": [{"role": "user", "content": user}]}).encode()
    base = env("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    req = urllib.request.Request(f"{base}/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
    except Exception as e:  # network or HTTP error
        raise LLMError(f"anthropic request failed: {e}") from e
    return "".join(b.get("text", "") for b in data["content"])


def extract_json(raw: str) -> dict:
    """Models sometimes wrap JSON in code fences or add a sentence around it."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model output")
    return json.loads(raw[start:end + 1])
