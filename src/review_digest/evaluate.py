"""Compare model labels with a hand-labelled gold file. Run it after every prompt or model change."""
import csv
from collections import defaultdict

from .config import THEMES


def load_gold(path: str) -> dict[str, set[tuple[str, str]]]:
    gold = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gold[row["id"]] = {tuple(x.split(":")) for x in row["labels"].split("|")}
    return gold


def compare(gold: dict[str, set], predicted: dict[str, set]) -> dict:
    tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
    sent_ok = sent_total = exact = 0
    misses = []
    for rid, g in gold.items():
        p = predicted.get(rid, set())
        g_themes, p_themes = {t for t, _ in g}, {t for t, _ in p}
        for t in g_themes & p_themes:
            tp[t] += 1
        for t in p_themes - g_themes:
            fp[t] += 1
        for t in g_themes - p_themes:
            fn[t] += 1
        gs, ps = dict(g), dict(p)
        for t in g_themes & p_themes:
            sent_total += 1
            sent_ok += gs[t] == ps[t]
        if g == p:
            exact += 1
        else:
            misses.append((rid, sorted(g), sorted(p)))
    per_theme = {}
    for t in THEMES:
        p_ = tp[t] / (tp[t] + fp[t]) if tp[t] + fp[t] else None
        r_ = tp[t] / (tp[t] + fn[t]) if tp[t] + fn[t] else None
        per_theme[t] = (p_, r_, tp[t] + fn[t])
    TP, FP, FN = sum(tp.values()), sum(fp.values()), sum(fn.values())
    prec, rec = TP / (TP + FP) if TP + FP else 0, TP / (TP + FN) if TP + FN else 0
    return {"precision": prec, "recall": rec, "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0,
            "sentiment_acc": sent_ok / sent_total if sent_total else 0, "exact": exact / len(gold),
            "per_theme": per_theme, "misses": misses}


def report(res: dict, texts: dict[str, str]) -> str:
    pct = lambda x: "  - " if x is None else f"{x * 100:3.0f}%"
    lines = [f"themes:    precision {res['precision']:.0%}  recall {res['recall']:.0%}  F1 {res['f1']:.0%}",
             f"sentiment: {res['sentiment_acc']:.0%} correct on themes found by both",
             f"exact match (all themes and signs): {res['exact']:.0%} of reviews", "",
             "theme         prec  recall  n"]
    lines += [f"{t:<13} {pct(p)}  {pct(r)}  {n}" for t, (p, r, n) in res["per_theme"].items() if n or p is not None]
    if res["misses"]:
        lines += ["", "disagreements (gold -> model):"]
        for rid, g, p in res["misses"]:
            fmt = lambda s: ",".join(f"{a}:{b}" for a, b in s)
            lines.append(f"  «{texts[rid][:60]}»  {fmt(g)}  ->  {fmt(p)}")
    return "\n".join(lines)
