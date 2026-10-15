"""Review sources. Every source returns the same plain dicts: id, date (ISO), sku, rating, text."""
import csv
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import date, datetime


def review_id(day: str, sku: str, text: str) -> str:
    return hashlib.sha1(f"{day}|{sku}|{text}".encode("utf-8")).hexdigest()[:8]


def parse_date(value: str, default_year: int | None = None) -> date:
    value = value.strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    # the example file in the brief uses "06.10" without a year
    return datetime.strptime(f"{value}.{default_year or date.today().year}", "%d.%m.%Y").date()


def load_csv(path: str, default_year: int | None = None) -> tuple[list[dict], list[str]]:
    """Read DATE,SKU,RATING,TEXT. Returns (reviews, skipped_reasons)."""
    reviews, skipped = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            text = row.get("text", "")
            try:
                day = parse_date(row["date"], default_year)
                rating = int(row["rating"])
                if not 1 <= rating <= 5:
                    raise ValueError("rating out of range")
            except (KeyError, ValueError) as e:
                skipped.append(f"line {n}: bad row ({e})")
                continue
            if not text:
                skipped.append(f"line {n}: empty text")
                continue
            sku = row.get("sku", "").upper()
            reviews.append({"id": review_id(day.isoformat(), sku, text), "date": day.isoformat(),
                            "sku": sku, "rating": rating, "text": text})
    return reviews, skipped


def fetch_wildberries(token: str, since: date, page: int = 1000) -> list[dict]:
    """Wildberries feedbacks API adapter (answered and unanswered).

    Not exercised against the live API in this repo: it needs a seller token.
    Shape follows the public docs: GET /api/v1/feedbacks?isAnswered=&take=&skip=
    """
    base = "https://feedbacks-api.wildberries.ru/api/v1/feedbacks"
    reviews = []
    for answered in ("false", "true"):
        skip = 0
        while True:
            query = urllib.parse.urlencode({"isAnswered": answered, "take": page, "skip": skip,
                                            "dateFrom": int(datetime.combine(since, datetime.min.time()).timestamp()),
                                            "order": "dateDesc"})
            req = urllib.request.Request(f"{base}?{query}", headers={"Authorization": token})
            with urllib.request.urlopen(req, timeout=30) as resp:
                batch = json.load(resp)["data"]["feedbacks"]
            for fb in batch:
                text = (fb.get("text") or "").strip()
                if not text:
                    continue
                day = fb["createdDate"][:10]
                sku = (fb.get("productDetails") or {}).get("supplierArticle", "") or str(fb.get("nmId", ""))
                reviews.append({"id": review_id(day, sku, text), "date": day, "sku": sku,
                                "rating": int(fb["productValuation"]), "text": text})
            if len(batch) < page:
                break
            skip += page
    return reviews
