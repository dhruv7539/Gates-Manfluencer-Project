"""
Add per-reply Source URL column to the 3 Twitter audience-comment Final
files (Agba, Deyemi, Shola). Mirrors what we did for the content-analysis
Twitter datasets: each comment gets the X URL of its own reply tweet.

The existing 'Reference Text/Context' column intentionally points to the
parent (creator's) tweet — preserved as-is.
"""
from pathlib import Path
import html
import re
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "Audience Analysis" / "Audience Comments - Raw"
FINAL = ROOT / "Audience Analysis" / "Audience Comments - Final"

NORM_RE = re.compile(r"\s+")


def norm(s: str) -> str:
    s = html.unescape(str(s))
    s = (s.replace("’", "'").replace("‘", "'")
          .replace("“", '"').replace("”", '"')
          .replace("…", "..."))
    return NORM_RE.sub(" ", s).strip().lower()


JOBS = [
    ("Agba John Doe", "Never Leave Marriage Because Husband Cheated"),
    ("Deyemi Okanlawon", "Stop Raping Women Response"),
    ("Shola", "7 Women Will Beg One Man to Marry"),
]


def backfill(creator: str, topic: str) -> None:
    final_path = FINAL / f"{creator}_{topic}.xlsx"
    raw_path = RAW / creator / f"{topic}.xlsx"

    raw = pd.read_excel(raw_path)
    raw["_norm"] = raw["text"].map(norm)
    lookup = {}
    for n, u in zip(raw["_norm"], raw["url"]):
        if n:
            lookup.setdefault(n, u)

    final = pd.read_excel(final_path)
    urls = []
    misses = 0
    for v in final["text"]:
        n = norm(v)
        u = lookup.get(n)
        if not u:
            u = next((link for nt, link in zip(raw["_norm"], raw["url"])
                      if n and (n in nt or nt in n)), None)
        if not u:
            misses += 1
        urls.append(u or "")

    if "Source URL" in final.columns:
        final["Source URL"] = urls
    else:
        insert_at = list(final.columns).index("text") + 1
        final.insert(insert_at, "Source URL", urls)

    final.to_excel(final_path, index=False)
    print(f"[done] {final_path.name}: {len(final)} rows, {misses} unmatched")


def main() -> None:
    for creator, topic in JOBS:
        backfill(creator, topic)


if __name__ == "__main__":
    main()
