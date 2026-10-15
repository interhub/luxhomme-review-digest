import json
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
    with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                                       data=body), timeout=30) as resp:
        data = json.load(resp)
    if not data.get("ok"):
        raise RuntimeError(f"telegram error: {data}")
    return data["result"]["message_id"]
