"""15-iteration audience theme coding using gpt-4o with the tightened codebook
from the 15-Pass Audit doc.

Per row, asks gpt-4o to assign:
  - PRIMARY topic theme (12 codes; OTHER not allowed; UNCLEAR for true edge cases)
  - up to 2 SECONDARY themes
  - AUDIENCE_STANCE (Support/Challenge/Mixed/Question/Testimony/Joke-casual)
  - RHETORICAL_STRATEGY (advice_rule | testimony | moral_warning | ridicule |
                         religious_appeal | whataboutism | common_sense_claim |
                         empathy_solidarity)
  - NORMATIVE_ORIENTATION (Progressive/Regressive/Mixed/Unclear)

Runs 15 iterations per row at temperatures [0.0, 0.3, 0.5] × 5 reps each.
Caches per (text_hash, iter_idx). Modal vote per field.

Outputs:
    temp/themes_15x_audience_gpt4o.parquet         (cache)
    Nigeria/Audience Analysis/Exploratory/themes_15x_results_gpt4o.parquet
"""
from __future__ import annotations
import asyncio, hashlib, json, os
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
CACHE_PATH  = ROOT / "temp" / "themes_15x_audience_gpt4o.parquet"
OUT_PARQUET = ROOT / "Nigeria" / "Audience Analysis" / "Exploratory" / "themes_15x_results_gpt4o.parquet"
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

CODES = [
    "MARRIAGE_FAMILY",
    "PROVIDER_STATUS",
    "AUTHORITY_SUBMISSION",
    "SEXUAL_MORALITY",
    "GBV_CONSENT",
    "TRAUMA_MENTAL_HEALTH",
    "PARTNERSHIP_EGALITARIAN",
    "GENDER_GRIEVANCE",
    "SELF_DISCIPLINE",
    "FAITH_MORAL_REPAIR",
    "RELATIONSHIP_TACTICS",
    "MASCULINITY_IDENTITY",
    "UNCLEAR",
]

STANCE = ["Support", "Challenge", "Mixed", "Question", "Testimony", "Joke-casual"]
RHET   = ["advice_rule", "testimony", "moral_warning", "ridicule",
          "religious_appeal", "whataboutism", "common_sense_claim", "empathy_solidarity"]
ORIENT = ["Progressive", "Regressive", "Mixed", "Unclear"]

# tightened codebook from the 15-Pass Audit
PROMPT = """You are coding short Nigerian masculinity-related social-media comments for a USC / Gates Foundation research project.

Use this TIGHTENED codebook. Decision rules are strict — follow them.

PRIMARY THEME (pick exactly one; pick the most central):

- MARRIAGE_FAMILY        marriage, divorce, infidelity, husband/wife, fatherhood/motherhood, child support, household duty.
                         Use when family/marriage is the concrete setting of the claim.
- PROVIDER_STATUS        money/income/career/status/respectability framed as proof of manhood or relationship worth.
                         Do NOT use when money is incidental and the real focus is submission or sexual morality.
- AUTHORITY_SUBMISSION   explicit hierarchy: obedience, submission, headship, control, surname, command, "men lead/women serve".
                         Requires explicit hierarchy/control language. Do NOT use for general family talk without hierarchy.
- SEXUAL_MORALITY        cheating, body count, abortion, pornography, BBL/body policing, female desirability/respectability,
                         sexual double standards. Do NOT use when rape/consent/abuse is central — use GBV_CONSENT.
- GBV_CONSENT            rape, consent, abuse, victim stigma, false accusations, molestation, prosecution.
                         Use for Deyemi anti-rape debates and false-accusation replies.
- TRAUMA_MENTAL_HEALTH   trauma, depression, grief, healing, emotional vulnerability, psychological harm.
                         Do NOT use just because the row says "painful" rhetorically — inner life must be central.
- PARTNERSHIP_EGALITARIAN  mutual respect, shared money/parenting, listening, allyship, healthy reciprocity.
                         Do NOT use for generic praise without a relational norm.
- GENDER_GRIEVANCE       women/feminists/equality framed as threat, scam, opportunism; gender-war; anti-modern-woman claims.
                         Requires generalized distrust, not specific criticism of one person.
- SELF_DISCIPLINE        personal responsibility, maturity, restraint, growth, learning/unlearning.
                         Do NOT use when "discipline" is only about controlling women.
- FAITH_MORAL_REPAIR     EXPLICIT faith/scripture/God/prayer/church/sin/testimony tied to masculinity, marriage, healing, or moral conduct.
                         Generic morality or "the truth" without religious frame does NOT qualify.
- RELATIONSHIP_TACTICS   tactical dating advice: scarcity, pursuit, availability, options, rejection, picking partners,
                         attraction strategy. Do NOT use for ordinary marriage talk or vague relationship praise.
- MASCULINITY_IDENTITY   direct talk about men/boys/manhood/masculinity as a group, male socialization.
                         Use as PRIMARY only if no more specific theme fits — it is an umbrella code.
- UNCLEAR                low-signal/off-topic/uncodable. Use sparingly — prefer a real theme when possible.

SECONDARY THEMES: 0–2 codes from the same list (no duplicates of primary).

AUDIENCE_STANCE (one of):
  Support | Challenge | Mixed | Question | Testimony | Joke-casual

RHETORICAL_STRATEGY (one of):
  advice_rule | testimony | moral_warning | ridicule | religious_appeal |
  whataboutism | common_sense_claim | empathy_solidarity

NORMATIVE_ORIENTATION (one of):
  Progressive | Regressive | Mixed | Unclear

Return JSON exactly in this shape:
{
  "primary": "<CODE>",
  "secondary": ["<CODE>", "<CODE>"],
  "stance": "<STANCE>",
  "rhetoric": "<STRATEGY>",
  "orientation": "<ORIENTATION>"
}
"""

LLM = "gpt-4o"
TEMPERATURES = [0.0, 0.3, 0.5]   # 3 temps × 5 reps = 15 iterations
REPS_PER_TEMP = 5
CONCURRENCY = 12

# ─── cache ──────────────────────────────────────────────────────────────────

def text_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]

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

# ─── coding ─────────────────────────────────────────────────────────────────

async def code_one(client, sem, text, temp):
    async with sem:
        try:
            r = await client.chat.completions.create(
                model=LLM,
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": text[:1800]},
                ],
                temperature=temp,
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            obj = json.loads(r.choices[0].message.content)
            prim = obj.get("primary", "UNCLEAR")
            if prim not in CODES: prim = "UNCLEAR"
            sec = [c for c in (obj.get("secondary") or []) if c in CODES and c != prim][:2]
            stance = obj.get("stance", "Mixed")
            if stance not in STANCE: stance = "Mixed"
            rhet = obj.get("rhetoric", "common_sense_claim")
            if rhet not in RHET: rhet = "common_sense_claim"
            orient = obj.get("orientation", "Unclear")
            if orient not in ORIENT: orient = "Unclear"
            return {"primary": prim, "secondary": sec,
                    "stance": stance, "rhetoric": rhet, "orientation": orient}
        except Exception as e:
            return {"primary": "UNCLEAR", "secondary": [],
                    "stance": "Mixed", "rhetoric": "common_sense_claim",
                    "orientation": "Unclear", "error": str(e)[:120]}

async def main():
    df = pd.read_parquet(AUD_PARQUET)
    print(f"loaded {len(df)} audience rows")

    texts = df["text_english"].tolist()
    hashes = [text_hash(t) for t in texts]

    cache = load_cache()
    print(f"cache has {len(cache)} entries")

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

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
    print(f"model: {LLM}")

    BATCH = 600
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
        primaries, secondaries, stances, rhets, orients = [], [], [], [], []
        for it in range(total_iters):
            r = cache.get((h, it), {})
            primaries.append(r.get("primary", "UNCLEAR"))
            secondaries.extend(r.get("secondary", []))
            stances.append(r.get("stance", "Mixed"))
            rhets.append(r.get("rhetoric", "common_sense_claim"))
            orients.append(r.get("orientation", "Unclear"))
        prim_c = Counter(primaries)
        sec_c = Counter(secondaries)
        modal_primary, mc = prim_c.most_common(1)[0]
        prim_stab = mc / total_iters
        modal_secs = [c for c, n in sec_c.items() if n / total_iters >= 0.30 and c != modal_primary][:2]
        modal_stance, sc = Counter(stances).most_common(1)[0]
        modal_rhet, rc = Counter(rhets).most_common(1)[0]
        modal_orient, oc = Counter(orients).most_common(1)[0]
        out_rows.append({
            "text_hash": h,
            "modal_primary": modal_primary,
            "primary_stability": round(prim_stab, 3),
            "primary_distribution": dict(prim_c),
            "modal_secondaries": modal_secs,
            "modal_stance": modal_stance,
            "stance_stability": round(sc/total_iters, 3),
            "modal_rhetoric": modal_rhet,
            "rhetoric_stability": round(rc/total_iters, 3),
            "modal_orientation": modal_orient,
            "orientation_stability": round(oc/total_iters, 3),
        })
    out = pd.DataFrame(out_rows)
    df = df.assign(text_hash=hashes).merge(out, on="text_hash", how="left")
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    print(f"wrote {OUT_PARQUET}")

    # ─── REPORT ──────────────────────────────────────────────────────────────
    n = len(df)
    print("\n" + "="*72)
    print(f"FINAL THEME DISTRIBUTION (n={n} comments, {total_iters} iters of {LLM})")
    print("="*72)

    print("\nPRIMARY theme counts:")
    print(df["modal_primary"].value_counts().to_string())

    print(f"\nMean primary stability across {total_iters} iters:",
          round(df["primary_stability"].mean(), 3))
    print("Stability buckets:")
    bins = pd.cut(df["primary_stability"], bins=[0, 0.5, 0.7, 0.85, 1.001],
                  labels=["unstable (<50%)", "weak (50-70%)", "ok (70-85%)", "stable (>85%)"])
    print(bins.value_counts().to_string())

    print("\nUNCLEAR rate:", (df["modal_primary"] == "UNCLEAR").sum(), "/", n,
          f"({(df['modal_primary']=='UNCLEAR').mean()*100:.1f}%)")

    print("\nPRIMARY × creator:")
    print(df.groupby(["creator", "modal_primary"]).size().unstack(fill_value=0).T.to_string())

    if "orientation" not in df.columns:
        OMAP = {"Banky Wellington": "progressive", "Deyemi Okanlawon": "progressive",
                "Agba John Doe": "regressive", "Shola": "regressive"}
        df["orientation"] = df["creator"].map(OMAP)
    print("\nPRIMARY × orientation:")
    print(df.groupby(["orientation", "modal_primary"]).size().unstack(fill_value=0).T.to_string())

    print("\nAUDIENCE_STANCE distribution:")
    print(df["modal_stance"].value_counts().to_string())

    print("\nRHETORICAL_STRATEGY distribution:")
    print(df["modal_rhetoric"].value_counts().to_string())

    print("\nNORMATIVE_ORIENTATION distribution (LLM-coded, vs creator-orientation):")
    print(df["modal_orientation"].value_counts().to_string())
    print("\nLLM-orientation × creator-orientation crosstab:")
    print(pd.crosstab(df["orientation"], df["modal_orientation"]).to_string())

    # combined frequency (primary + secondary)
    print("\nCOMBINED primary+secondary frequency:")
    bag = []
    for _, r in df.iterrows():
        bag.append(r["modal_primary"])
        bag.extend(r["modal_secondaries"])
    print(pd.Series(bag).value_counts().to_string())

if __name__ == "__main__":
    asyncio.run(main())
