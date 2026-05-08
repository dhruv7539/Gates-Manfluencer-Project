"""25-iteration audience theme coding with ChatGPT's 13-code codebook.

Reads Nigeria/Audience Analysis/Translated/audience_final_translated.parquet,
asks gpt-4o-mini to assign primary + secondary themes from the 13-code list,
runs 25 iterations per row at varied temperatures, takes modal vote.

Output:
    temp/themes_25x_audience.parquet
    Nigeria/Audience Analysis/Exploratory/themes_25x_results.parquet
    stdout: aggregate distribution + per-creator + stability metrics
"""
from __future__ import annotations
import asyncio, hashlib, json, os, sys
from pathlib import Path
from collections import Counter

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

AUD_PARQUET = ROOT / "Nigeria" / "Audience Analysis" / "Translated" / "audience_final_translated.parquet"
CACHE_PATH  = ROOT / "temp" / "themes_25x_audience.parquet"
OUT_PARQUET = ROOT / "Nigeria" / "Audience Analysis" / "Exploratory" / "themes_25x_results.parquet"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

CODES = [
    "MARRIAGE_FAMILY",
    "MASCULINITY_IDENTITY",
    "RELATIONSHIP_TACTICS",
    "GBV_CONSENT",
    "SEXUAL_MORALITY",
    "PROVIDER_STATUS",
    "GENDER_GRIEVANCE",
    "TRAUMA_MENTAL_HEALTH",
    "PARTNERSHIP_EGALITARIAN",
    "FAITH_MORAL_REPAIR",
    "AUTHORITY_SUBMISSION",
    "SELF_DISCIPLINE",
    "OTHER",
]

PROMPT = f"""You are coding short Nigerian masculinity-related social-media comments for a USC / Gates Foundation research project.

Pick the SINGLE primary theme (the one most central to the comment) and 0-2 secondary themes from this controlled vocabulary:

- MARRIAGE_FAMILY        Marriage, divorce, infidelity, child support, fatherhood/motherhood, domestic duties
- MASCULINITY_IDENTITY   Direct talk about being a man, manhood, male socialization
- RELATIONSHIP_TACTICS   Dating advice, pursuit, scarcity, availability, chasing, relationship strategy
- GBV_CONSENT            Rape, consent, abuse, victim protection/stigma, false accusation
- SEXUAL_MORALITY        Body count, cheating, abortion, BBL, body policing, female desirability/respectability
- PROVIDER_STATUS        Money/career/status as proof of manhood or relationship worth
- GENDER_GRIEVANCE       Distrust of women/feminism, gender-war framing, anti-modern-woman rhetoric
- TRAUMA_MENTAL_HEALTH   Male emotional expression, trauma, depression, healing, vulnerability
- PARTNERSHIP_EGALITARIAN  Mutual respect, shared money/parenting, equality, non-dominating partnership
- FAITH_MORAL_REPAIR     God, scripture, prayer, sin, spiritual testimony tied to gender/masculinity
- AUTHORITY_SUBMISSION   Male headship, female submission, hierarchy, control
- SELF_DISCIPLINE        Self-control, maturity, growth, habit formation, learning/unlearning
- OTHER                  None of the above is a meaningful fit

Return JSON: {{"primary": "<CODE>", "secondary": ["<CODE>", "<CODE>"]}}
Use only codes from the list. Empty secondary array is fine.
"""

LLM = "gpt-4o-mini"
TEMPERATURES = [0.0, 0.3, 0.5, 0.7, 1.0]   # 5 temps × 5 reps = 25 iterations
REPS_PER_TEMP = 5
CONCURRENCY = 16

# ─── cache ──────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if CACHE_PATH.exists():
        c = pd.read_parquet(CACHE_PATH)
        return {(r.text_hash, r.iter_idx): json.loads(r.result_json) for r in c.itertuples()}
    return {}

def save_cache(cache: dict) -> None:
    rows = [
        {"text_hash": k[0], "iter_idx": k[1], "result_json": json.dumps(v, ensure_ascii=False)}
        for k, v in cache.items()
    ]
    pd.DataFrame(rows).to_parquet(CACHE_PATH, index=False)

def text_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

# ─── coding ─────────────────────────────────────────────────────────────────

async def code_one(client: AsyncOpenAI, sem: asyncio.Semaphore, text: str, temp: float) -> dict:
    async with sem:
        try:
            r = await client.chat.completions.create(
                model=LLM,
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": text[:1800]},
                ],
                temperature=temp,
                max_tokens=120,
                response_format={"type": "json_object"},
            )
            obj = json.loads(r.choices[0].message.content)
            prim = obj.get("primary", "OTHER")
            if prim not in CODES: prim = "OTHER"
            sec = [c for c in obj.get("secondary", []) if c in CODES and c != prim][:2]
            return {"primary": prim, "secondary": sec}
        except Exception as e:
            return {"primary": "OTHER", "secondary": [], "error": str(e)[:120]}

async def main():
    df = pd.read_parquet(AUD_PARQUET)
    print(f"loaded {len(df)} audience rows")

    texts = df["text_english"].tolist()
    hashes = [text_hash(t) for t in texts]

    cache = load_cache()
    print(f"cache has {len(cache)} entries")

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    # build job list
    jobs = []
    iter_idx = 0
    for temp in TEMPERATURES:
        for rep in range(REPS_PER_TEMP):
            for h, t in zip(hashes, texts):
                key = (h, iter_idx)
                if key not in cache:
                    jobs.append((key, t, temp))
            iter_idx += 1
    total_iters = iter_idx
    print(f"total iterations per row: {total_iters}; jobs to run: {len(jobs)}")

    # run
    BATCH = 500
    for i in range(0, len(jobs), BATCH):
        batch = jobs[i:i+BATCH]
        tasks = [code_one(client, sem, t, temp) for _, t, temp in batch]
        results = await atqdm.gather(*tasks, desc=f"batch {i//BATCH+1}")
        for (key, _, _), res in zip(batch, results):
            cache[key] = res
        save_cache(cache)
        print(f"  saved cache: {len(cache)} entries")

    # aggregate per row
    print("\n=== aggregating modal votes ===")
    out_rows = []
    for h, t in zip(hashes, texts):
        primaries, secondaries = [], []
        for it in range(total_iters):
            r = cache.get((h, it), {"primary": "OTHER", "secondary": []})
            primaries.append(r["primary"])
            secondaries.extend(r.get("secondary", []))
        prim_counter = Counter(primaries)
        sec_counter = Counter(secondaries)
        modal_primary, modal_count = prim_counter.most_common(1)[0]
        stability = modal_count / total_iters
        # secondaries: any code that appeared in >= 30% of runs as secondary
        modal_secondaries = [c for c, n in sec_counter.items() if n / total_iters >= 0.30 and c != modal_primary][:2]
        out_rows.append({
            "text_hash": h,
            "modal_primary": modal_primary,
            "primary_stability": round(stability, 3),
            "primary_distribution": dict(prim_counter),
            "modal_secondaries": modal_secondaries,
        })
    out = pd.DataFrame(out_rows)

    # join back to audience df
    df = df.assign(text_hash=hashes).merge(out, on="text_hash", how="left")
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    print(f"wrote {OUT_PARQUET}")

    # ─── REPORT ──────────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print(f"FINAL THEME DISTRIBUTION (n={len(df)} comments, {total_iters} iterations each)")
    print("="*70)
    print("\nPRIMARY theme counts:")
    print(df["modal_primary"].value_counts().to_string())

    print("\nMean stability of primary theme across 25 iterations:",
          round(df["primary_stability"].mean(), 3))
    print("\nStability buckets:")
    bins = pd.cut(df["primary_stability"], bins=[0, 0.5, 0.7, 0.85, 1.001],
                  labels=["unstable (<50%)", "weak (50-70%)", "ok (70-85%)", "stable (>85%)"])
    print(bins.value_counts().to_string())

    print("\nPRIMARY × creator:")
    print(df.groupby(["creator", "modal_primary"]).size().unstack(fill_value=0).T.to_string())

    print("\nPRIMARY × orientation:")
    if "orientation" not in df.columns:
        ORIENT = {
            "Banky Wellington": "progressive", "Deyemi Okanlawon": "progressive",
            "Agba John Doe": "regressive", "Shola": "regressive",
        }
        df["orientation"] = df["creator"].map(ORIENT)
    print(df.groupby(["orientation", "modal_primary"]).size().unstack(fill_value=0).T.to_string())

    # combined primary + secondary frequency
    print("\nCOMBINED primary+secondary frequency (any role):")
    all_assigned = []
    for _, r in df.iterrows():
        all_assigned.append(r["modal_primary"])
        all_assigned.extend(r["modal_secondaries"])
    print(pd.Series(all_assigned).value_counts().to_string())

if __name__ == "__main__":
    asyncio.run(main())
