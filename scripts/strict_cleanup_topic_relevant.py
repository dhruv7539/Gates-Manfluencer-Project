"""Second-pass strict cleanup of Topic Relevant Comments.

Reviewer feedback flagged 8 files as needing cleanup for noise, 1-line reactions,
clapbacks, off-topic gender-war banter, inter-commenter arguments, and repetitive
low-substance comments. Four files are deemed clean and are left untouched.

Applied rule: keep a comment only if it reveals stance, interpretation, lived
experience, or reasoned audience meaning-making. Borderline cases are dropped.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

TRC = ROOT / "Topic Relevant Comments"
CACHE_DIR = ROOT / "temp" / "strict_cleanup"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

LLM_MODEL = "gpt-4o-mini"
LLM_BATCH_SIZE = 20
LLM_CONCURRENCY = 16
DEDUP_SIMILARITY = 0.92
EMBED_MODEL = "text-embedding-3-large"
EMBED_BATCH_SIZE = 256

# Tiers per reviewer feedback
HEAVY_CLEANUP = {
    "Kenya/Amerix_A Woman Cant Love a Man.xlsx",
    "Kenya/Amerix_Stay Away From Vulgar Women.xlsx",
    "Kenya/Andrew Kibe_I Wonder How Some Men Are Satisfied.xlsx",
    "Nigeria/Deyemi Okanlawon_Stop Raping Women Response.xlsx",
    "Nigeria/Shola_7 Women Will Beg One Man to Marry.xlsx",
    "Nigeria/Wizarab_Sex Toys and Raping Young Boys.xlsx",
}
LIGHT_CLEANUP = {
    "Nigeria/Agba John Doe_Never Leave Marriage Because Husband Cheated.xlsx",
    "Kenya/Eddy Kimani_Young Man Thinks Its A Shame Not Having A Car At 35.xlsx",
}
LEAVE_AS_IS = {
    "Nigeria/Banky Wellington_Final Say Faith.xlsx",
    "Nigeria/Banky Wellington_My Story Journey Through Hope and Faith.xlsx",
    "Kenya/Onyango Otieno_My Voice Was Beaten Out of Me.xlsx",
    "Kenya/Philip Karanja_Girl Dad Episode 1.xlsx",
}

STRICT_SYSTEM_PROMPT = """You are a qualitative research reviewer enforcing a strict filter on audience comments from Nigerian and Kenyan social media posts about masculinity, gender, relationships, marriage, faith, or sexual violence.

KEEP a comment ONLY if it shows real audience meaning-making: a stance, interpretation, reasoning, lived experience, cultural observation, or substantive engagement with the post's argument. Acceptable keepers typically give a reason for their view, describe a personal or observed experience, interpret the creator's claim, or offer nuanced agreement/disagreement.

REMOVE a comment if it is ANY of these (be strict — err toward removal on borderline cases):
- One-line hype or reaction: "facts", "real", "exactly", "this is true", "women are finished", "men are finished", "bitter truth", "gbam", "spot on", "nice one".
- Pure insults, mockery, abuse, or name-calling with no reasoning.
- Off-topic gender-war banter that does not engage the specific post.
- A reply arguing with another commenter rather than responding to the creator or the post.
- A repetitive stance-assertion without reasoning ("women should endure", "men are the prize", "women are evil") that adds no nuance.
- Generic motivational filler with no masculinity / gender / relationship content specific to the post.
- A comment that mentions the topic but reveals no stance, interpretation, lived experience, or reasoning.
- Single-sentence agreement or disagreement with no backing reason.

A substantive comment is typically at least two clauses long and either (a) explains why, (b) gives a concrete example or lived experience, (c) offers a cultural or religious interpretation, or (d) names a causal mechanism.

Return ONLY a JSON object: {"results": [{"id": <int>, "keep": true|false, "reason": "<=12 words"}]}. Output nothing else."""


def batch_user_prompt(batch):
    lines = ["Review these comments. For each, judge keep/remove per the rubric.", ""]
    for i, text in batch:
        safe = str(text).replace("\n", " ")[:500]
        lines.append(f"[{i}] {safe}")
    return "\n".join(lines)


async def classify_batch(task_key, local_to_global, batch, sem, async_client):
    async with sem:
        for attempt in range(4):
            try:
                resp = await async_client.chat.completions.create(
                    model=LLM_MODEL,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": STRICT_SYSTEM_PROMPT},
                        {"role": "user", "content": batch_user_prompt(batch)},
                    ],
                )
                data = json.loads(resp.choices[0].message.content)
                out = []
                for r in data.get("results", []):
                    lid = r.get("id")
                    if lid in local_to_global:
                        out.append((local_to_global[lid], bool(r.get("keep")), r.get("reason", "")))
                return task_key, out
            except Exception as e:
                if attempt == 3:
                    return task_key, [(local_to_global[i], None, f"error: {e}") for i, _ in batch]
                await asyncio.sleep(2 ** attempt)


async def classify_all(texts):
    async_client = AsyncOpenAI()
    sem = asyncio.Semaphore(LLM_CONCURRENCY)
    coroutines = []
    for start in range(0, len(texts), LLM_BATCH_SIZE):
        chunk = list(enumerate(texts[start:start + LLM_BATCH_SIZE], start=start))
        local_to_global = {li: gi for gi, (li, _) in enumerate(chunk, start=start)}
        # local_to_global should map from local_id (which is `gi` since we use enumerate with start)
        # Actually we passed (i, text) where i is already the global index; simplify:
        local_to_global = {gi: gi for gi, _ in chunk}
        task_key = len(coroutines)
        coroutines.append(classify_batch(task_key, local_to_global, chunk, sem, async_client))
    all_rows = []
    tasks = [asyncio.create_task(c) for c in coroutines]
    for fut in atqdm.as_completed(tasks, total=len(tasks), desc="filter"):
        _, rows = await fut
        all_rows.extend(rows)
    return {gi: (keep, reason) for gi, keep, reason in all_rows}


def embed_all(texts, client):
    emb_list = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        chunk = texts[start:start + EMBED_BATCH_SIZE]
        r = client.embeddings.create(model=EMBED_MODEL, input=chunk)
        emb_list.append(np.array([d.embedding for d in r.data]))
    return np.vstack(emb_list)


def semantic_dedup(df_texts, threshold=DEDUP_SIMILARITY, client=None):
    """Greedy dedup: keep longest per near-duplicate cluster (cosine >= threshold)."""
    if len(df_texts) <= 1:
        return list(range(len(df_texts)))
    emb = embed_all(df_texts, client)
    emb = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    sim = emb @ emb.T
    np.fill_diagonal(sim, -1.0)
    keep_mask = [True] * len(df_texts)
    # For each pair above threshold, keep the longer comment
    order = sorted(range(len(df_texts)), key=lambda i: -len(df_texts[i]))
    kept = set()
    for i in order:
        if not keep_mask[i]:
            continue
        kept.add(i)
        for j in range(len(df_texts)):
            if j == i or not keep_mask[j]:
                continue
            if sim[i, j] >= threshold:
                keep_mask[j] = False
    return [i for i, k in enumerate(keep_mask) if k]


def process_file(path: Path, tier: str):
    rel = str(path.relative_to(TRC)).replace("\\", "/")
    df = pd.read_excel(path)
    if "text" not in df.columns:
        print(f"  skip {rel}: no 'text' column")
        return None
    before = len(df)
    texts = df["text"].astype(str).tolist()

    # LLM strict filter
    key = rel.replace("/", "__")
    cache = CACHE_DIR / f"{key}.json"
    if cache.exists():
        cached = json.loads(cache.read_text())
        verdicts = {int(k): tuple(v) for k, v in cached.items()}
    else:
        verdicts = asyncio.run(classify_all(texts))
        cache.write_text(json.dumps({str(k): list(v) for k, v in verdicts.items()}))

    keep_idx = [i for i in range(len(texts)) if verdicts.get(i, (False,))[0]]
    llm_kept = [texts[i] for i in keep_idx]

    # Semantic dedup only for heavy tier
    if tier == "heavy" and llm_kept:
        client = OpenAI()
        keep_positions = semantic_dedup(llm_kept, client=client)
        final_texts = [llm_kept[i] for i in keep_positions]
    else:
        final_texts = llm_kept

    out = pd.DataFrame({"text": final_texts})
    out.to_excel(path, index=False)
    after = len(out)
    print(f"  [{tier:<5}] {rel:<80}  {before} -> {after}  ({after/before:.0%} kept)")
    return {"file": rel, "tier": tier, "before": before, "after": after}


def main():
    results = []
    targets = []
    for f in sorted(TRC.rglob("*.xlsx")):
        if f.name.startswith("_") or f.name.startswith("~$"):
            continue
        rel = str(f.relative_to(TRC)).replace("\\", "/")
        if rel in HEAVY_CLEANUP:
            targets.append((f, "heavy"))
        elif rel in LIGHT_CLEANUP:
            targets.append((f, "light"))
        elif rel in LEAVE_AS_IS:
            print(f"  [skip ] {rel} (leave-as-is)")
        else:
            print(f"  [?    ] {rel} (unknown tier — skipping)")

    for path, tier in targets:
        r = process_file(path, tier)
        if r:
            results.append(r)

    summary = pd.DataFrame(results)
    summary.to_excel(TRC / "_cleanup_report.xlsx", index=False)
    print("\nSummary:")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
