import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT / "prompts" / "classify.md"

# theme id -> (label shown to the team, hint for the model)
THEMES = {
    "perf": ("Работа и результат", "как техника выполняет свою задачу: вкус кофе, всасывание, мощность, готовка; сюда же «застревает», «путается», «плохо убирает»"),
    "durability": ("Надёжность и качество", "поломки, не включается, греется, материалы, износ, брак в работе"),
    "noise": ("Шум", "громкость работы"),
    "delivery": ("Доставка", "сроки доставки, работа курьера, коробку бросили или помяли по дороге"),
    "packaging": ("Упаковка и вид при получении", "вещь пришла с царапинами или повреждённой коробкой, не хватает комплектации"),
    "usability": ("Удобство и дизайн", "уход, мытьё, габариты, управление, внешний вид, крышки, программы; не про то, справляется ли техника с задачей"),
    "price": ("Цена и ценность", "дорого, дёшево, стоит своих денег"),
    "support": ("Поддержка и гарантия", "ответы поддержки, возвраты, гарантийные случаи"),
    "software": ("Приложение и подключение", "мобильное приложение, wifi, карты, обновления"),
    "general": ("Общее впечатление", "оценка без предметных деталей: «супер», «ок», «хлам»"),
    "other": ("Другое", "спам, реклама, отзыв не про товар"),
}
SENTIMENTS = ("pos", "neg", "neu")

# themes that are not shown as a standalone complaint or praise in the digest
SOFT_THEMES = {"general", "other"}


def prompt_text() -> str:
    lines = [f"- {tid}: {label}. {hint}" for tid, (label, hint) in THEMES.items()]
    return PROMPT_PATH.read_text(encoding="utf-8").replace("{{THEMES}}", "\n".join(lines))


def prompt_version() -> str:
    return hashlib.sha1(prompt_text().encode("utf-8")).hexdigest()[:8]


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)
