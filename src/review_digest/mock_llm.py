"""Keyword baseline. Only for tests, offline demos and as the floor in `eval`: never for a real digest."""
import json

RULES = {
    "noise": (("шум", "громк", "loud", "noisy"), ("тих", "тише")),
    "delivery": (("доставк", "курьер", "привезли", "приехал", "доставили"), ()),
    "durability": (("перестал", "перестала", "сломал", "включается через раз", "греется", "пахнет",
                    "мутнеет"), ("отлично уже", "работает отлично")),
    "packaging": (("коробк", "царапин", "помят", "упаковк"), ()),
    "price": (("цена", "дорого", "дороговато", "денег", "кусается"), ()),
    "support": (("поддержк", "деньги вернули", "гарант"), ()),
    "software": (("приложени", "вайфай", "wifi", "карту не"), ()),
    "usability": (("удобн", "моется", "дизайн", "крышка", "места занимает", "программы"), ()),
    "perf": (("быстро", "вкусн", "мощн", "собирает", "застрев", "застрял", "кофе", "блендер", "готовит",
              "крошит", "убирает", "карту строит", "работает"), ()),
}
NEG_WORDS = ("но ", "перестал", "сломал", "застрев", "застрял", "шумит", "громк", "ужасн", "кусается",
             "бросил", "через раз", "не отвечает", "глюч", "вылетает", "дороговато", "тугая", "греется",
             "пахнет", "мутнеет", "помят", "царапин", "дней", "хлам", "возвращаю", "занимает", "loud")
POS_WORDS = ("быстро", "вкусн", "мощн", "удобн", "легко", "отлично", "супер", "классн", "лучший", "хруст",
             "довольн", "идеально", "рекомендую", "нравится", "стоит", "тихий", "огонь", "доволен")


def _sentiment(text: str, theme: str) -> str:
    low = text.lower()
    if any(w in low for w in RULES[theme][1]):
        return "pos"
    if theme == "noise" or any(w in low for w in NEG_WORDS):
        return "neg"
    return "pos" if any(w in low for w in POS_WORDS) else "neu"


def classify_batch(user: str) -> str:
    results = []
    for item in json.loads(user)["reviews"]:
        low = item["text"].lower()
        themes = [{"theme": t, "sentiment": _sentiment(item["text"], t)}
                  for t, (keys, _) in RULES.items() if any(k in low for k in keys)]
        if not themes:
            themes = [{"theme": "general", "sentiment": "pos" if item["rating"] >= 4 else "neg"
                       if item["rating"] <= 2 else "neu"}]
        results.append({"id": item["id"], "themes": themes, "other_label": None, "confidence": 0.7})
    return json.dumps({"results": results}, ensure_ascii=False)
