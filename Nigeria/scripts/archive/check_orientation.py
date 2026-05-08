"""Classify every row across all 5 Final files as progressive / regressive / neutral.

Goal: verify that:
  - Banky Wellington (PROGRESSIVE) and Deyemi Okanlawon (PROGRESSIVE) files
    are indeed dominated by progressive masculinity content.
  - Shola, Wizarab, Agba John Doe (REGRESSIVE) files are indeed dominated by
    regressive / patriarchal / manosphere-adjacent masculinity content.

For each row, send to gpt-4o with strict definitions, get back:
  {orientation: progressive|regressive|neutral, reason: <one sentence>}

Then report per-file distribution + list every row whose orientation contradicts
the creator's expected orientation.

Output: temp/orientation_audit.xlsx (every row × verdict) + console report.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

FINAL = ROOT / "Nigeria" / "Content Analysis" / "Content - Final"
AUDIT_OUT = ROOT / "temp" / "orientation_audit.xlsx"
AUDIT_OUT.parent.mkdir(parents=True, exist_ok=True)

LLM_MODEL   = "gpt-4o"
CONCURRENCY = 6

EXPECTED = {
    "Banky Wellington_Podcast.xlsx":    "progressive",
    "Deyemi Okanlawon_Twitter.xlsx":    "progressive",
    "Shola_Twitter.xlsx":               "regressive",
    "Wizarab_Twitter.xlsx":             "regressive",
    "Agba John Doe_Twitter.xlsx":       "regressive",
}

PROMPT = """You are coding a Nigerian masculinity content analysis (Norman Lear Center / Gates Foundation).

Classify the SNIPPET below on its dominant gender stance:

PROGRESSIVE = challenges patriarchal norms; advocates male accountability, male emotional life, vulnerability, mental health, shared partnership, gender equality, female agency, victim protection, fatherhood as presence, anti-rape culture, anti-double-standards, anti-hypergamy-blaming, anti-"men are scum" deflection, men supporting women.

REGRESSIVE = reinforces patriarchal / soft-patriarchal / manosphere norms; female submission, men-as-prize, hypergamy resentment, women as transactional / users / unfaithful, sexual double standards, anti-feminism, "men will be men", scarcity narrative, simp-shaming, women's-place-is-home, marital authority of husbands, anti-women cynicism.

NEUTRAL = describes a phenomenon without taking a side; pure observation; a question; ambiguous joke; mixed message; or content that is gender-related but does not advocate either stance.

Important: judge the SNIPPET'S stance, not the speaker's general reputation.

SNIPPET:
\"\"\"{text}\"\"\"

JSON only:
{{"orientation": "progressive" | "regressive" | "neutral",
  "confidence": "high" | "medium" | "low",
  "reason": "<one short sentence — name the specific signal>"}}"""


async def classify(client, sem, text):
    async with sem:
        for attempt in range(5):
            try:
                resp = await client.chat.completions.create(
                    model=LLM_MODEL, temperature=0,
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": PROMPT.format(text=text[:1800])}],
                )
                return json.loads(resp.choices[0].message.content)
            except Exception as e:
                err = str(e)
                if "429" in err or "rate" in err.lower():
                    await asyncio.sleep(5 * (2 ** attempt))
                    continue
                if attempt == 4:
                    return {"orientation": "neutral", "confidence": "low", "reason": f"err: {err[:100]}"}
                await asyncio.sleep(2 ** attempt)


async def main():
    print("=== orientation audit (gpt-4o) ===", flush=True)
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    audit_rows = []
    for fname, expected in EXPECTED.items():
        path = FINAL / fname
        df = pd.read_excel(path)
        print(f"\n  {fname:<40} ({len(df)} rows, expect={expected})…", flush=True)
        coros = [classify(client, sem, str(t)) for t in df['Verbatim Text (CODE THIS)']]
        results = await atqdm.gather(*coros, desc=fname[:20])
        for (_, row), r in zip(df.iterrows(), results):
            audit_rows.append({
                "file":      fname,
                "expected":  expected,
                "Segment ID": row['Segment ID'],
                "orientation": r.get("orientation", "neutral"),
                "confidence":  r.get("confidence", "low"),
                "reason":      r.get("reason", ""),
                "text":        str(row['Verbatim Text (CODE THIS)'])[:300],
            })

    audit = pd.DataFrame(audit_rows)
    audit.to_excel(AUDIT_OUT, index=False)
    print(f"\n  audit → {AUDIT_OUT.relative_to(ROOT)}", flush=True)

    # Per-file summary
    print("\n=== per-file orientation distribution ===\n", flush=True)
    for fname, expected in EXPECTED.items():
        sub = audit[audit['file'] == fname]
        n = len(sub)
        counts = sub['orientation'].value_counts()
        prog = counts.get('progressive', 0)
        regr = counts.get('regressive', 0)
        neut = counts.get('neutral', 0)
        match = prog if expected == 'progressive' else regr
        contra = regr if expected == 'progressive' else prog
        pct_match = 100 * match / n if n else 0
        pct_contra = 100 * contra / n if n else 0
        print(f"  {fname:<40} expect={expected:<11} prog={prog:>3}  regr={regr:>3}  neut={neut:>3}   match={pct_match:>5.1f}%  contradict={pct_contra:>5.1f}%")

    # Contradictions
    print("\n=== rows that CONTRADICT expected orientation (high/medium conf only) ===\n", flush=True)
    for fname, expected in EXPECTED.items():
        sub = audit[(audit['file'] == fname)
                    & (audit['orientation'].isin(['progressive','regressive']))
                    & (audit['orientation'] != expected)
                    & (audit['confidence'].isin(['high','medium']))]
        print(f"\n--- {fname} ({len(sub)} contradicting rows) ---")
        for _, r in sub.iterrows():
            print(f"  {r['Segment ID']} [{r['orientation']}/{r['confidence']}]: {r['reason']}")
            print(f"     text: {r['text'][:200]}")


if __name__ == "__main__":
    asyncio.run(main())
