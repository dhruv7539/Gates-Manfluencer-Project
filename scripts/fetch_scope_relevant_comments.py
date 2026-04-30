"""Two-tier scope filter for audience comments.

Pipeline per video:
  1. LLM classifies each comment into KEEP_TIER_1 / KEEP_TIER_2 / DROP
  2. Length filter (>= MIN_CHARS / MIN_WORDS)

Sampling rule per (country, orientation):
  - REGRESSIVE creators -> Tier-1 only (cap at TARGET_PER_ORIENT if exceeded)
  - PROGRESSIVE creators -> Tier-1 first; if total < TARGET_PER_ORIENT, supplement
    with Tier-2 (sorted by length desc as a quality proxy) until target reached.

Output per file (Scope Relevant Comments/<Country>/<Creator>_<Video>.xlsx):
  text | author | tier | topic_tag | reason_kept | orientation_source
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

CACHE_DIR = ROOT / "temp" / "scope_filter"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR = ROOT / "Scope Relevant Comments"
OUT_DIR.mkdir(parents=True, exist_ok=True)

LLM_MODEL = "gpt-4o-mini"
LLM_BATCH_SIZE = 20
LLM_CONCURRENCY = 16

MIN_CHARS = 100
MIN_WORDS = 15

# Target sample size per orientation (combined across that orientation's creators)
TARGET_PER_ORIENT = 500

PROGRESSIVE = {
    "Nigeria": ["Banky Wellington", "Deyemi Okanlawon"],
    "Kenya":   ["Philip Karanja", "Onyango Otieno", "Eddy Kimani"],
}
REGRESSIVE = {
    "Nigeria": ["Agba John Doe", "Shola", "Wizarab"],
    "Kenya":   ["Amerix", "Andrew Kibe"],
}

SCOPE_SYSTEM_PROMPT = """You are a qualitative research reviewer filtering audience comments for a study of MASCULINITY-RELATED MEDIA in Nigeria and Kenya. The study examines audience reception of MASCULINITY AS A TOPIC: how men behave, what makes a man, opposition to women/feminism, male role models, gender norms, male accountability.

Classify each comment into one of THREE categories:

KEEP_TIER_1 = clearly in-scope masculinity/gender-norm discourse
The comment makes a substantive observation, claim, argument, or first-person testimony about ANY of:
- A. Manosphere & traditional masculinity tropes (alpha/sigma/real-man, provider, hypergamy, marriage market, anti-feminist framings)
- B. Gender-debate & accountability (rape / sexual violence, false-accusation framings, male defensiveness, "not all men", boy-child protection, men-holding-men accountable)
- C. Male behavior, role, identity (what men "should" do, gendered marriage critique, fatherhood as a role, men-vs-women generalizations with reasoning)
- D. Male emotional life AS A PHENOMENON or substantive lived experience (vulnerability, mental health, porn struggle, addiction, male grief tied to gendered framing)

KEEP_TIER_2 = weaker but still useful audience reception of masculinity, especially on PROGRESSIVE creator content
The comment is not deeply analytical but does communicate audience reception of a masculinity model. Examples:
- "More men should support women like this"
- "This is what a real man looks like"
- "Men need to learn from him"
- "He is showing young men how to be responsible"
- "This kind of father/husband/support is rare"
- "Men should be emotionally open like this"
- Brief gendered observations without deep reasoning ("African men think cheating is normal")
- Audience endorsement / critique of the creator's masculinity framing
Tier-2 captures meaningful audience-reception data on healthier masculinity role-modeling that is shorter / less analytical than Tier-1 but still on-topic.

DROP = out of scope, even if it mentions marriage / men / faith
NEVER keep these:
- Pure faith praise ("Amen", "God is faithful", "great testimony", "I tap into this")
- Personal prayer requests ("I want a husband", "may God bless me with a child")
- Couple admiration with no gender claim ("Beautiful couple", "I want a marriage like yours")
- Personal grief/loss with no gendered framing ("I lost my baby in 2019")
- Generic compliments / hype ("nice video", "love you sir", "more grace")
- Single-clause reactions ("facts", "true", "exactly", "100%")
- Off-topic, self-promo, spam
- Inter-commenter arguments unrelated to gender

For each KEPT comment also assign exactly ONE topic_tag from this list:
  masculine_norms, anti_women, anti_feminism, gender_debate, male_emotion,
  marriage_relationships, fatherhood, male_victim, progressive_role_model

For DROP, set topic_tag to "" and reason_kept to "" .

Return ONLY JSON: {"results": [{"id": <int>, "keep_status": "KEEP_TIER_1"|"KEEP_TIER_2"|"DROP", "topic_tag": "<tag>", "reason_kept": "<one short sentence, <=14 words>"}]}"""


def batch_user_prompt(batch):
    lines = ["Classify each comment per the rubric.", ""]
    for i, text in batch:
        safe = str(text).replace("\n", " ")[:500]
        lines.append(f"[{i}] {safe}")
    return "\n".join(lines)


async def classify_batch(batch, sem, client):
    async with sem:
        for attempt in range(4):
            try:
                resp = await client.chat.completions.create(
                    model=LLM_MODEL,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SCOPE_SYSTEM_PROMPT},
                        {"role": "user", "content": batch_user_prompt(batch)},
                    ],
                )
                data = json.loads(resp.choices[0].message.content)
                out = []
                for r in data.get("results", []):
                    gid = r.get("id")
                    if gid is None:
                        continue
                    keep_status = str(r.get("keep_status", "DROP")).upper()
                    if keep_status not in ("KEEP_TIER_1", "KEEP_TIER_2", "DROP"):
                        keep_status = "DROP"
                    topic = str(r.get("topic_tag", ""))[:40]
                    reason = str(r.get("reason_kept", ""))[:120]
                    out.append((int(gid), keep_status, topic, reason))
                return out
            except Exception as e:
                if attempt == 3:
                    return [(gi, "ERROR", "", f"error: {str(e)[:80]}") for gi, _ in batch]
                await asyncio.sleep(2 ** attempt)


async def classify_all(texts):
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(LLM_CONCURRENCY)
    coroutines = []
    for start in range(0, len(texts), LLM_BATCH_SIZE):
        chunk = list(enumerate(texts[start:start + LLM_BATCH_SIZE], start=start))
        coroutines.append(classify_batch(chunk, sem, client))
    verdicts = {}
    tasks = [asyncio.create_task(c) for c in coroutines]
    for fut in atqdm.as_completed(tasks, total=len(tasks), desc="filter"):
        rows = await fut
        for gid, status, topic, reason in rows:
            verdicts[gid] = (status, topic, reason)
    return verdicts


def safe_name(s: str) -> str:
    return re.sub(r"[^\w\- ]+", "", s).strip()


def collect_video_records(country: str, creator: str, video_path: Path):
    """Run LLM (with caching) and return per-comment records that pass length filter."""
    video_stem = video_path.stem
    cache_key = f"{country}__{safe_name(creator)}__{safe_name(video_stem)}.json"
    cache_path = CACHE_DIR / cache_key

    df = pd.read_excel(video_path)
    if "comment" in df.columns:
        text_col = "comment"
    elif "text" in df.columns:
        text_col = "text"
    else:
        raise ValueError(f"{video_path}: no 'comment' or 'text' column")
    raw_texts = df[text_col].astype(str).tolist()
    cleaned = [re.sub(r"\s+", " ", re.sub(r"@\w+", "", t)).strip() for t in raw_texts]
    n = len(cleaned)
    authors = df["author"].astype(str).tolist() if "author" in df.columns else [""] * n

    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        verdicts = {int(k): tuple(v) for k, v in cached.items()}
        bad = [i for i in range(n) if i not in verdicts or verdicts[i][0] == "ERROR"]
        if bad:
            print(f"  cache: re-running {len(bad)} bad/missing entries")
            new = asyncio.run(classify_all([cleaned[i] for i in bad]))
            for local_i, gid in enumerate(bad):
                verdicts[gid] = new.get(local_i, ("ERROR", "", "missing"))
            cache_path.write_text(json.dumps({str(k): list(v) for k, v in verdicts.items()}))
    else:
        verdicts = asyncio.run(classify_all(cleaned))
        cache_path.write_text(json.dumps({str(k): list(v) for k, v in verdicts.items()}))

    records = []
    for i in range(n):
        v = verdicts.get(i)
        if not v:
            continue
        status, topic, reason = v
        if status not in ("KEEP_TIER_1", "KEEP_TIER_2"):
            continue
        t = cleaned[i]
        if len(t) < MIN_CHARS or len(t.split()) < MIN_WORDS:
            continue
        records.append({
            "country": country,
            "creator": creator,
            "video": video_stem,
            "text": t,
            "author": authors[i],
            "tier": "T1" if status == "KEEP_TIER_1" else "T2",
            "topic_tag": topic,
            "reason_kept": reason,
        })
    return records, n


def apply_orientation_sampling(records: list, orientation: str) -> list:
    """REG: T1 only (capped at TARGET). PROG: T1 + best T2 until TARGET reached."""
    t1 = [r for r in records if r["tier"] == "T1"]
    t2 = [r for r in records if r["tier"] == "T2"]

    if orientation == "regressive":
        sample = sorted(t1, key=lambda r: -len(r["text"]))
        if len(sample) > TARGET_PER_ORIENT:
            sample = sample[:TARGET_PER_ORIENT]
            print(f"  [REG] T1={len(t1)} (capped to {TARGET_PER_ORIENT}); T2 ignored ({len(t2)} avail)")
        else:
            print(f"  [REG] T1={len(t1)} (all kept); T2 ignored ({len(t2)} avail)")
        return sample

    # progressive
    sample = list(t1)
    if len(sample) >= TARGET_PER_ORIENT:
        sample = sorted(sample, key=lambda r: -len(r["text"]))[:TARGET_PER_ORIENT]
        print(f"  [PROG] T1={len(t1)} (capped to {TARGET_PER_ORIENT}); T2 ignored ({len(t2)} avail)")
        return sample
    needed = TARGET_PER_ORIENT - len(sample)
    t2_sorted = sorted(t2, key=lambda r: -len(r["text"]))
    sample.extend(t2_sorted[:needed])
    used_t2 = min(needed, len(t2))
    print(f"  [PROG] T1={len(t1)} + T2={used_t2} (of {len(t2)} avail) = {len(sample)} (target {TARGET_PER_ORIENT})")
    return sample


def write_per_video_outputs(country: str, sampled_records: list, orientation: str):
    out_country_dir = OUT_DIR / country
    out_country_dir.mkdir(parents=True, exist_ok=True)
    grouped = {}
    for r in sampled_records:
        grouped.setdefault((r["creator"], r["video"]), []).append(r)
    written = []
    for (creator, video), rows in grouped.items():
        out_df = pd.DataFrame(rows)
        out_df["orientation_source"] = orientation
        out_df = out_df[["text", "author", "tier", "topic_tag", "reason_kept", "orientation_source"]]
        name = f"{safe_name(creator)}_{safe_name(video)}.xlsx"
        path = out_country_dir / name
        out_df.to_excel(path, index=False)
        written.append((str(path.relative_to(ROOT)), len(out_df)))
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", choices=["Nigeria", "Kenya"], required=True)
    ap.add_argument("--orientation", choices=["progressive", "regressive", "all"], default="all")
    args = ap.parse_args()

    src_root = ROOT / f"{args.country} Audience Comments"
    if not src_root.exists():
        raise SystemExit(f"Missing source folder: {src_root}")

    orientations = ["progressive", "regressive"] if args.orientation == "all" else [args.orientation]
    grand_summary = []

    for orient in orientations:
        creators = (PROGRESSIVE if orient == "progressive" else REGRESSIVE).get(args.country, [])
        all_records = []
        funnel_rows = []
        for creator in creators:
            cdir = src_root / creator
            if not cdir.exists():
                print(f"  ! missing creator folder: {cdir}")
                continue
            for vfile in sorted(cdir.glob("*.xlsx")):
                if vfile.name.startswith("~$"):
                    continue
                print(f"\n=== {orient.upper()} / {creator} / {vfile.stem} ===")
                records, n_in = collect_video_records(args.country, creator, vfile)
                t1 = sum(1 for r in records if r["tier"] == "T1")
                t2 = sum(1 for r in records if r["tier"] == "T2")
                print(f"  n_in={n_in}  t1_after_length={t1}  t2_after_length={t2}")
                funnel_rows.append({
                    "orientation": orient, "creator": creator, "video": vfile.stem,
                    "n_in": n_in, "t1": t1, "t2": t2,
                })
                all_records.extend(records)

        sampled = apply_orientation_sampling(all_records, orient)
        written = write_per_video_outputs(args.country, sampled, orient)
        for path, n in written:
            print(f"  wrote {path}: {n} rows")

        funnel = pd.DataFrame(funnel_rows)
        funnel.to_excel(OUT_DIR / f"_funnel_{args.country}_{orient}.xlsx", index=False)
        grand_summary.append({
            "orientation": orient,
            "n_total_kept": len(sampled),
            "n_t1": sum(1 for r in sampled if r["tier"] == "T1"),
            "n_t2": sum(1 for r in sampled if r["tier"] == "T2"),
        })
        print(f"\n[{orient.upper()}] FINAL kept: {len(sampled)} (T1={sum(1 for r in sampled if r['tier']=='T1')} T2={sum(1 for r in sampled if r['tier']=='T2')})")

    sumdf = pd.DataFrame(grand_summary)
    sumdf.to_excel(OUT_DIR / f"_summary_{args.country}.xlsx", index=False)
    print("\n========================================")
    print(sumdf.to_string(index=False))


if __name__ == "__main__":
    main()
