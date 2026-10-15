import argparse
import sys
from datetime import date

from . import analyze, digest, evaluate, sources, store, telegram
from .config import ROOT, env

DB_DEFAULT = str(ROOT / "output" / "reviews.db")


def _db(args):
    import os
    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    return store.connect(args.db)


def _week(args) -> date:
    return digest.week_of(date.fromisoformat(args.week)) if args.week else digest.last_full_week()


def cmd_ingest(args):
    conn = _db(args)
    if args.wildberries:
        token = env("WB_FEEDBACKS_TOKEN")
        if not token:
            sys.exit("set WB_FEEDBACKS_TOKEN")
        reviews, skipped = sources.fetch_wildberries(token, date.fromisoformat(args.since)), []
    else:
        reviews, skipped = sources.load_csv(args.csv, args.default_year)
    added = store.add_reviews(conn, reviews)
    print(f"ingest: {len(reviews)} rows read, {added} new, {len(skipped)} skipped")
    for s in skipped:
        print("  skipped:", s)


def cmd_analyze(args):
    print("analyze:", analyze.run(_db(args), force=args.force, provider=args.provider))


def cmd_digest(args):
    data, text = digest.make(_db(args), _week(args))
    print(text)
    if args.send:
        conn = _db(args)
        msg_id = telegram.send(text)
        conn.execute("INSERT INTO runs (week_start, text, created_at, sent_at, telegram_message_id)"
                     " VALUES (?,?,?,?,?)", (data["week_start"], text, store.now(), store.now(), msg_id))
        conn.commit()
        print(f"\nsent to Telegram, message id {msg_id}")


def cmd_run(args):
    cmd_ingest(args)
    cmd_analyze(args)
    cmd_digest(args)


def cmd_flagged(args):
    for r in store.analyzed_reviews(_db(args)):
        if r["flags"]:
            print(f"{r['id']} {r['date']} {r['sku']} {r['rating']}★ {','.join(r['flags'])}: {r['text']}")


def cmd_eval(args):
    import os
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "eval.db")
    conn = store.connect(path)
    reviews, _ = sources.load_csv(args.csv, args.default_year)
    store.add_reviews(conn, reviews)
    print("eval:", analyze.run(conn, provider=args.provider))
    gold = evaluate.load_gold(args.gold)
    rows = store.analyzed_reviews(conn)
    if len(rows) < len(gold):
        sys.exit(f"only {len(rows)} of {len(gold)} reviews were labelled, fix the errors above first")
    predicted = {r["id"]: {(t["theme"], t["sentiment"]) for t in r["themes"]} for r in rows}
    res = evaluate.compare(gold, predicted)
    print(evaluate.report(res, {r["id"]: r["text"] for r in reviews}))
    if res["f1"] < args.min_f1:
        sys.exit(f"F1 {res['f1']:.2f} is below the threshold {args.min_f1}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="review_digest", description=__doc__)
    p.add_argument("--db", default=DB_DEFAULT)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    def source_args(sp):
        sp.add_argument("--csv", default=str(ROOT / "data" / "reviews.csv"))
        sp.add_argument("--default-year", type=int, default=2026)
        sp.add_argument("--wildberries", action="store_true", help="pull from the Wildberries API instead of a CSV")
        sp.add_argument("--since", default=date.today().replace(day=1).isoformat())

    sp = add("ingest", cmd_ingest, "load reviews into the database")
    source_args(sp)
    sp = add("analyze", cmd_analyze, "label new reviews with the LLM")
    sp.add_argument("--force", action="store_true", help="relabel everything (after a prompt change)")
    sp.add_argument("--provider", choices=["anthropic", "replay", "mock"])
    sp = add("digest", cmd_digest, "build the weekly digest")
    sp.add_argument("--week", help="any date inside the week, default: last full week")
    sp.add_argument("--send", action="store_true", help="send to Telegram (needs TELEGRAM_* env)")
    sp = add("run", cmd_run, "ingest + analyze + digest in one go (what the scheduler calls)")
    source_args(sp)
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--provider", choices=["anthropic", "replay", "mock"])
    sp.add_argument("--week")
    sp.add_argument("--send", action="store_true")
    add("flagged", cmd_flagged, "list reviews that need a human look")
    sp = add("eval", cmd_eval, "score the model against data/gold_labels.csv")
    sp.add_argument("--csv", default=str(ROOT / "data" / "reviews.csv"))
    sp.add_argument("--gold", default=str(ROOT / "data" / "gold_labels.csv"))
    sp.add_argument("--default-year", type=int, default=2026)
    sp.add_argument("--provider", choices=["anthropic", "replay", "mock"])
    sp.add_argument("--min-f1", type=float, default=0.0)

    args = p.parse_args(argv)
    args.fn(args)
    return 0
