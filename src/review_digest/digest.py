"""Weekly aggregation. All numbers and all quotes come from code, never from the model."""
import html
from collections import Counter
from datetime import date, timedelta

from . import store
from .config import SOFT_THEMES, THEMES

QUOTE_MAX = 110
TOP_COMPLAINTS = 4
MIN_SIGNAL = 3  # fewer mentions than this is shown as a number, never as a trend


def week_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def last_full_week(today: date | None = None) -> date:
    return week_of(today or date.today()) - timedelta(days=7)


def label(theme: str) -> str:
    return THEMES[theme][0]


def clip(text: str, limit: int = QUOTE_MAX) -> str:
    """Cut on a word boundary. The result is always a verbatim prefix of the source, plus an ellipsis."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0].rsplit(" ", 1)[0].rstrip(",.;: ") + "…"


def split_weeks(rows: list[dict], week_start: date) -> tuple[list[dict], list[dict]]:
    cur_from, prev_from = week_start.isoformat(), (week_start - timedelta(days=7)).isoformat()
    cur_to = (week_start + timedelta(days=7)).isoformat()
    cur = [r for r in rows if cur_from <= r["date"] < cur_to]
    prev = [r for r in rows if prev_from <= r["date"] < cur_from]
    return cur, prev


def theme_stats(rows: list[dict]) -> dict[str, dict]:
    stats = {t: {"pos": [], "neg": [], "neu": []} for t in THEMES}
    for r in rows:
        for t in r["themes"]:
            stats[t["theme"]][t["sentiment"]].append(r)
    return stats


def scored(rows: list[dict]) -> list[dict]:
    """Rows that describe the product: spam and ads (only the `other` theme) must not move averages."""
    return [r for r in rows if any(t["theme"] != "other" for t in r["themes"])]


def avg(rows: list[dict]) -> float | None:
    return round(sum(r["rating"] for r in rows) / len(rows), 1) if rows else None


def pick_quotes(reviews: list[dict], n: int = 2, used: set | None = None) -> list[dict]:
    """Worst rating first, then the most informative (longest) text; prefer different SKUs
    and reviews not already quoted under another theme."""
    used = used if used is not None else set()
    ranked = sorted(reviews, key=lambda r: (r["id"] in used, r["rating"], -len(r["text"]), r["date"]))
    picked, skus = [], set()
    for r in ranked:
        if len(picked) < n and (r["sku"] not in skus or len(skus) >= len({x["sku"] for x in ranked})):
            picked.append(r)
            skus.add(r["sku"])
    for r in ranked:
        if len(picked) < n and r not in picked:
            picked.append(r)
    used.update(r["id"] for r in picked)
    return picked


def quote_of(r: dict) -> dict:
    q = clip(r["text"])
    assert r["text"].startswith(q.rstrip("…")), "quote must be verbatim"
    return {"text": q, "sku": r["sku"], "rating": r["rating"], "id": r["id"]}


def sku_share(reviews: list[dict]) -> str:
    c = Counter(r["sku"] for r in reviews)
    sku, n = c.most_common(1)[0]
    return f"{sku}: {n} из {len(reviews)}" if len(c) > 1 or n < len(reviews) else f"все {n} - {sku}"


def build(rows: list[dict], week_start: date, unanalyzed: int = 0) -> dict:
    cur, prev = split_weeks(rows, week_start)
    cs, ps = theme_stats(cur), theme_stats(prev)
    hard = [t for t in THEMES if t not in SOFT_THEMES]

    complaints, used = [], set()
    for t in sorted(hard, key=lambda t: -len(cs[t]["neg"])):
        neg = cs[t]["neg"]
        if neg and len(complaints) < TOP_COMPLAINTS:
            complaints.append({"theme": t, "count": len(neg), "prev": len(ps[t]["neg"]),
                               "skus": sku_share(neg), "quotes": [quote_of(r) for r in pick_quotes(neg, 2, used)]})

    praise = []
    for t in sorted(hard, key=lambda t: -len(cs[t]["pos"])):
        pos = cs[t]["pos"]
        if pos and len(praise) < 2:
            best = sorted(pos, key=lambda r: (-r["rating"], -len(r["text"])))[:1]
            praise.append({"theme": t, "count": len(pos), "quotes": [quote_of(r) for r in best]})

    changes = []
    for t in hard:
        now, before = len(cs[t]["neg"]), len(ps[t]["neg"])
        if now >= MIN_SIGNAL and before == 0:
            changes.append({"kind": "new", "theme": t, "prev": before, "now": now, "skus": sku_share(cs[t]["neg"])})
        elif now >= MIN_SIGNAL and now - before >= 2:
            changes.append({"kind": "up", "theme": t, "prev": before, "now": now, "skus": sku_share(cs[t]["neg"])})
        elif before >= MIN_SIGNAL and before - now >= 2:
            changes.append({"kind": "down", "theme": t, "prev": before, "now": now, "skus": ""})
    changes.sort(key=lambda c: -(c["now"] - c["prev"]))

    by_theme = []
    for t in sorted(THEMES, key=lambda t: -(len(cs[t]["pos"]) + len(cs[t]["neg"]) + len(cs[t]["neu"]))):
        pos, neg, neu = len(cs[t]["pos"]), len(cs[t]["neg"]), len(cs[t]["neu"])
        if pos + neg + neu and t != "other":
            by_theme.append({"theme": t, "total": pos + neg + neu, "pos": pos, "neg": neg, "neu": neu})

    cur_s, prev_s = scored(cur), scored(prev)
    sku_moves = []
    for sku in sorted({r["sku"] for r in cur_s}):
        a, b = [r for r in cur_s if r["sku"] == sku], [r for r in prev_s if r["sku"] == sku]
        if len(a) >= MIN_SIGNAL and b and abs(avg(a) - avg(b)) >= 0.8:
            sku_moves.append({"sku": sku, "now": avg(a), "prev": avg(b), "n": len(a)})

    flagged = [r for r in cur if r["flags"]]
    return {"week_start": week_start.isoformat(), "week_end": (week_start + timedelta(days=6)).isoformat(),
            "total": len(cur), "prev_total": len(prev), "avg": avg(cur_s), "prev_avg": avg(prev_s),
            "by_theme": by_theme, "complaints": complaints, "praise": praise, "changes": changes, "sku_moves": sku_moves,
            "flagged": len(flagged), "mismatch": sum("rating_mismatch" in r["flags"] for r in flagged),
            "unanalyzed": unanalyzed}


def _d(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"


def render(d: dict, limit: int = 4000) -> str:
    """Telegram HTML. If the text is too long the second quote of each complaint is dropped first."""
    for quotes_per_item in (2, 1, 0):
        text = _render(d, quotes_per_item)
        if len(text) <= limit:
            return text
    return text[:limit].rsplit("\n", 1)[0]


def _q(q: dict) -> str:
    return f"«{html.escape(q['text'])}» ({html.escape(q['sku'])}, {q['rating']}★)"


def _render(d: dict, qn: int) -> str:
    if not d["total"]:
        text = f"📊 <b>Отзывы Luxhommè: {_d(d['week_start'])} - {_d(d['week_end'])}</b>\n\nРазобранных отзывов за неделю нет."
        if d["unanalyzed"]:
            text += f"\n⚠️ Не разобрано из-за сбоя модели: {d['unanalyzed']}"
        return text
    out = [f"📊 <b>Отзывы Luxhommè: {_d(d['week_start'])} - {_d(d['week_end'])}</b>", ""]
    prev = f"; неделей ранее {d['prev_total']}, оценка {d['prev_avg']}" if d["prev_total"] else "; прошлой недели для сравнения нет"
    out.append(f"Отзывов: {d['total']}, средняя оценка {d['avg']}{prev}")
    out += ["", "📋 <b>Отзывов по темам</b> (один отзыв может быть в нескольких)"]
    for b in d["by_theme"]:
        out.append(f"• {label(b['theme'])}: {b['total']} (жалоб {b['neg']}, похвал {b['pos']})")
    if d["complaints"]:
        out += ["", "🔥 <b>На что жалуются</b>"]
        for i, c in enumerate(d["complaints"], 1):
            out.append(f"{i}. <b>{label(c['theme'])}</b>: {c['count']} (неделей ранее {c['prev']}), {html.escape(c['skus'])}")
            out += [f"   {_q(q)}" for q in c["quotes"][:qn]]
    if d["praise"]:
        out += ["", "👍 <b>Что хвалят</b>"]
        for p in d["praise"]:
            out.append(f"• <b>{label(p['theme'])}</b>: {p['count']}")
            out += [f"   {_q(q)}" for q in p["quotes"][:min(qn, 1)]]
    moves = []
    icons = {"new": "🆕 впервые заметно", "up": "📈 растёт", "down": "📉 стало лучше"}
    for c in d["changes"]:
        extra = f", {html.escape(c['skus'])}" if c["skus"] else ""
        moves.append(f"{icons[c['kind']]}: {label(c['theme'])}, жалоб {c['prev']} → {c['now']}{extra}")
    for m in d["sku_moves"]:
        moves.append(f"{'⬇️' if m['now'] < m['prev'] else '⬆️'} {html.escape(m['sku'])}: средняя оценка {m['prev']} → {m['now']} ({m['n']} отзывов)")
    if moves:
        out += ["", "🔄 <b>Что изменилось к прошлой неделе</b>"] + moves
    notes = []
    if d["flagged"]:
        notes.append(f"🧐 На ручную проверку: {d['flagged']}" + (f" (оценка не совпадает с текстом: {d['mismatch']})" if d["mismatch"] else ""))
    if d["unanalyzed"]:
        notes.append(f"⚠️ Не разобрано из-за сбоя модели: {d['unanalyzed']}")
    return "\n".join(out + ([""] + notes if notes else []))


def make(conn, week_start: date) -> tuple[dict, str]:
    data = build(store.analyzed_reviews(conn), week_start, store.count_unanalyzed(conn, week_start.isoformat(), (week_start + timedelta(days=7)).isoformat()))
    return data, render(data)
