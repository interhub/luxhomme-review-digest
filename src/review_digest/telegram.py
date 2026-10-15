import json
import urllib.error
import urllib.parse
import urllib.request

from .config import env


def send(text: str) -> int:
    """Send an HTML message to the configured chat. Returns the Telegram message id."""
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (see .env.example)")
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"telegram HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
    if not data.get("ok"):
        raise RuntimeError(f"telegram error: {data}")
    return data["result"]["message_id"]
