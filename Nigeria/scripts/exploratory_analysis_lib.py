"""
Shared library for exploratory LLM analyses on the Nigeria audience + content
datasets. One generic batched async runner with on-disk caching, plus task
prompts for each analysis Ksenia approved.

Used by Nigeria/Notebooks/Exploratory Analysis.ipynb.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import nest_asyncio
import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
nest_asyncio.apply()

CACHE_DIR = ROOT / "temp" / "exploratory_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

LLM_MODEL    = "gpt-4o-mini"
CONCURRENCY  = 12
BATCH_SIZE   = 12        # rows per LLM call
MAX_CHARS    = 1500      # truncate over-long inputs

# ─── caching ─────────────────────────────────────────────────────────────────

def _hash_input(text: str, analysis: str) -> str:
    return hashlib.sha1(f"{analysis}::{text.strip()}".encode("utf-8")).hexdigest()


def load_cache(analysis: str) -> dict[str, dict]:
    p = CACHE_DIR / f"{analysis}.parquet"
    if not p.exists():
        return {}
    df = pd.read_parquet(p)
    return {r["hash"]: json.loads(r["result_json"]) for _, r in df.iterrows()}


def save_cache(analysis: str, cache: dict[str, dict]):
    rows = [{"hash": h, "result_json": json.dumps(v)} for h, v in cache.items()]
    pd.DataFrame(rows).to_parquet(CACHE_DIR / f"{analysis}.parquet", index=False)


# ─── generic batched LLM runner ──────────────────────────────────────────────

async def _run_batch(
    client: AsyncOpenAI,
    sem: asyncio.Semaphore,
    system_prompt: str,
    batch: list[tuple[int, str]],
    response_schema_hint: str = "",
) -> list[dict | None]:
    async with sem:
        items = "\n".join(f"{i}. {t[:MAX_CHARS]}" for i, t in batch)
        user_msg = (
            f"Analyse the following items.\n"
            f"Return STRICT JSON with this structure:\n"
            f'{{"results": [{{"id": <int>, ...}}]}}\n'
            "Every object MUST include the matching id from the input. Return one result per item, in the SAME ORDER.\n"
            + (f"Each result object must also contain: {response_schema_hint}\n" if response_schema_hint else "")
            + f"\nITEMS:\n{items}"
        )
        try:
            r = await client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            raw = r.choices[0].message.content
        except Exception as e:
            print(f"  batch API failed: {type(e).__name__}: {str(e)[:120]}")
            return [None] * len(batch)

        try:
            data = json.loads(raw)
        except Exception as e:
            print(f"  batch JSON parse failed: {str(e)[:120]}; raw[:200]={raw[:200]!r}")
            return [None] * len(batch)

        results = data.get("results") or []
        if not isinstance(results, list):
            return [None] * len(batch)

        # try by-id first
        by_id: dict = {}
        for x in results:
            if isinstance(x, dict) and ("id" in x):
                by_id[x.get("id")] = x

        out: list[dict | None] = []
        used_positional = False
        for pos, (idx, _t) in enumerate(batch):
            x = by_id.get(idx) or by_id.get(str(idx))
            if x is None:
                # positional fallback: model dropped IDs but returned items in order
                if pos < len(results) and isinstance(results[pos], dict):
                    x = results[pos]
                    used_positional = True
            out.append(x if isinstance(x, dict) else None)

        # If positional fallback was used but lengths mismatched, warn once
        if used_positional and len(results) != len(batch):
            print(f"  warn: response had {len(results)} results for batch of {len(batch)} (positional fallback used)")
        return out


async def _run_analysis(
    texts: list[str],
    analysis: str,
    system_prompt: str,
    schema_hint: str = "",
) -> list[dict]:
    cache = load_cache(analysis)
    results: list[dict | None] = [None] * len(texts)
    pending: list[tuple[int, str]] = []

    for i, t in enumerate(texts):
        if not t or not str(t).strip():
            results[i] = {}
            continue
        t = str(t)
        h = _hash_input(t, analysis)
        if h in cache:
            results[i] = cache[h]
        else:
            pending.append((i, t))

    print(f"  [{analysis}] cached: {len(texts) - len(pending)}/{len(texts)}, calling LLM for: {len(pending)}")

    if pending:
        client = AsyncOpenAI()
        sem = asyncio.Semaphore(CONCURRENCY)
        # pack into batches of BATCH_SIZE
        batches = [pending[i:i + BATCH_SIZE] for i in range(0, len(pending), BATCH_SIZE)]

        async def go(batch):
            local = [(j, t) for j, (_orig, t) in enumerate(batch)]
            r = await _run_batch(client, sem, system_prompt, local, schema_hint)
            return batch, r

        all_results = await atqdm.gather(*[go(b) for b in batches])
        for batch, r in all_results:
            for (orig_i, t), entry in zip(batch, r):
                if entry is not None:
                    results[orig_i] = entry
                    cache[_hash_input(t, analysis)] = entry
                else:
                    results[orig_i] = {}
        save_cache(analysis, cache)

    return [r if r is not None else {} for r in results]


def run_analysis(texts: list[str], analysis: str, system_prompt: str, schema_hint: str = "") -> pd.DataFrame:
    """Sync entrypoint for notebooks. Returns DataFrame aligned to input order."""
    out = asyncio.run(_run_analysis(texts, analysis, system_prompt, schema_hint))
    df = pd.DataFrame(out)
    return df


# ─── analysis prompts ────────────────────────────────────────────────────────
# Each prompt is tightly scoped: small enum values, short strings, low cardinality.
# This keeps LLM output stable and cheap to aggregate.

PROMPTS = {
    # ── shared (audience + content) ──────────────────────────────────────────

    "themes": dict(
        prompt="""You are coding short pieces of Nigerian masculinity-related social media content for a USC / Gates Foundation research project.

For each item, identify the 1–3 dominant themes from this controlled vocabulary:
  - male_authority_provider     (man as head, provider, breadwinner, leader)
  - female_submission_role      (women must submit, traditional gender roles)
  - male_sexual_entitlement     (cheating, polygamy, "men will be men")
  - female_blame                (blaming women for divorce, harm, men's behavior)
  - male_accountability         (men must be accountable, self-reflect, change)
  - male_emotional_life         (men's feelings, vulnerability, mental health)
  - fatherhood_parenting        (raising sons/daughters, fatherly duty)
  - marriage_relationships      (dating, marriage advice, conflict, fidelity)
  - sexual_violence             (rape, sexual assault, consent)
  - hookup_transactional_sex    (sex work, money-for-sex, "runs girls")
  - religion_morality           (faith, sin, god, prayer)
  - economic_pressure           (money, bills, masculinity-and-money pressure)
  - feminism_gender_equality    (feminism, gender equality, women's rights)
  - homosexuality_lgbtq         (gay, queer, lgbt-related)
  - off_topic_or_generic        (greetings, generic praise, spam, unrelated)

Return: {"themes": ["...", "..."]} — list 1–3 codes from the vocabulary above, ordered by salience.""",
        schema_hint='"themes": [string]',
    ),

    "sentiment": dict(
        prompt="""You are coding sentiment for Nigerian social media text.

For each item, return:
  - sentiment: one of "positive" | "neutral" | "negative" | "mixed"
  - intensity: integer 1–5 (1=very mild, 5=very strong)

Return: {"sentiment": "...", "intensity": <int>}""",
        schema_hint='"sentiment": "positive|neutral|negative|mixed", "intensity": <1-5>',
    ),

    "emotion": dict(
        prompt="""You are coding emotional content. Identify the dominant emotion(s) expressed.

Use this controlled vocabulary (Plutchik-derived):
  joy, anger, sadness, fear, disgust, surprise, trust, anticipation, contempt, pride, shame, none

For each item, return up to 2 emotions, ordered by intensity.

Return: {"emotions": ["..."]}""",
        schema_hint='"emotions": [string, ...]',
    ),

    "ner": dict(
        prompt="""Extract named entities from each item. Use these types only:
  - PERSON   (named individuals: "Banky W", "Tonto Dikeh")
  - ORG      (organisations, brands, churches)
  - LOC      (places: "Lagos", "Nigeria")
  - HANDLE   (@-mentions, hashtags)

Return: {"entities": [{"text": "...", "type": "..."}, ...]}  — empty list if none.""",
        schema_hint='"entities": [{"text": str, "type": "PERSON|ORG|LOC|HANDLE"}]',
    ),

    "hate_speech": dict(
        prompt="""Code each item for hate speech / dehumanising language directed at a group.

Return:
  - hate_speech: true | false
  - target_group: one of "women" | "men" | "lgbtq" | "ethnic_religious" | "none"
  - severity: 0 (none) | 1 (mild slur/stereotype) | 2 (clear dehumanising) | 3 (incitement)

Return: {"hate_speech": bool, "target_group": "...", "severity": <int>}""",
        schema_hint='"hate_speech": bool, "target_group": str, "severity": 0-3',
    ),

    "toxicity": dict(
        prompt="""Score each item for toxicity / abusive language regardless of target.

Return:
  - toxicity: float 0.0–1.0  (0=clean, 1=extremely toxic)
  - categories: list, any of ["insult","profanity","threat","sexual","identity_attack"]

Return: {"toxicity": <float>, "categories": ["..."]}""",
        schema_hint='"toxicity": float 0..1, "categories": [string]',
    ),

    "misogyny": dict(
        prompt="""Code each item for misogynistic / sexist content (gender-based harm directed at women or femininity).

Use these subtypes from sexism research:
  - none
  - hostile_misogyny       (insults, dehumanisation: "all women are X")
  - benevolent_sexism      (women are pure/fragile/need-protection framing)
  - role_prescription      ("women should submit/cook/obey")
  - sexual_objectification (reducing women to sexual function)
  - victim_blaming         (women caused their own harm)

Return: {"misogyny": "<subtype>", "intensity": <0-3>}  (0=not present, 3=extreme)""",
        schema_hint='"misogyny": str, "intensity": 0-3',
    ),

    "moral_foundations": dict(
        prompt="""Code each item using Moral Foundations Theory. Identify which foundations are invoked.

Foundations:
  - care_harm       (compassion, suffering, protection)
  - fairness_cheat  (justice, equality, unfair treatment)
  - loyalty_betray  (group loyalty, betrayal, in-group)
  - authority_subversion (respect, tradition, hierarchy)
  - sanctity_degrad (purity, religion, contamination, disgust at impurity)
  - liberty_oppress (freedom from coercion, anti-domination)

For each item, return up to 2 foundations invoked. If none, return [].

Return: {"foundations": ["..."]}""",
        schema_hint='"foundations": [string]',
    ),

    # ── audience-leaning ─────────────────────────────────────────────────────

    "stance": dict(
        prompt="""You are coding audience reception. Each comment is a reply to a post by a Nigerian creator on masculinity / gender.

Code the comment's stance toward the post / creator's message:
  - support           (agrees, endorses, amplifies the message)
  - oppose            (disagrees, pushes back, critiques)
  - mixed             (agrees with parts, disagrees with others)
  - neutral           (factual, observational, no stance)
  - off_topic         (does not engage with the message at all)

Return: {"stance": "...", "confidence": "low|medium|high"}""",
        schema_hint='"stance": str, "confidence": "low|medium|high"',
    ),

    # ── content-leaning ──────────────────────────────────────────────────────

    "framing": dict(
        prompt="""You are doing framing analysis on a Nigerian creator's content (tweet / podcast snippet).

How is the masculinity / gender issue framed? Choose ONE primary frame:
  - male_victimhood        (men as victims of women, feminism, system)
  - female_blame           (women as cause of dysfunction)
  - male_accountability    (men should self-reflect / change)
  - gender_equality        (equal treatment, fairness frame)
  - traditional_order      (defending traditional hierarchy as natural/good)
  - self_improvement       (personal growth, "be a better man")
  - economic_pragmatism    (money / provider logic frames the argument)
  - religious_moral        (faith / morality framing)
  - other

Return: {"frame": "...", "stance_implied": "regressive|progressive|mixed|neutral"}""",
        schema_hint='"frame": str, "stance_implied": str',
    ),

    "argument_mining": dict(
        prompt="""Extract the argumentative structure of each item (a tweet / podcast snippet).

Return:
  - claim          : the core claim being made (<=20 words)  OR ""
  - reasoning_type : one of "anecdote" | "appeal_to_tradition" | "appeal_to_religion" | "appeal_to_data" | "appeal_to_authority" | "rhetorical_question" | "no_argument"
  - justification  : the justification given (<=25 words)  OR ""

Return: {"claim": "...", "reasoning_type": "...", "justification": "..."}""",
        schema_hint='"claim": str, "reasoning_type": str, "justification": str',
    ),
}


def run(texts: list[str], analysis: str) -> pd.DataFrame:
    """Convenience: looks up prompt by name and runs."""
    if analysis not in PROMPTS:
        raise ValueError(f"unknown analysis '{analysis}'. Available: {sorted(PROMPTS)}")
    spec = PROMPTS[analysis]
    return run_analysis(texts, analysis, spec["prompt"], spec.get("schema_hint", ""))


# ─── embedding-based emergent topic clustering ───────────────────────────────
# Uses text-embedding-3-small ($0.02/1M tokens) → UMAP → HDBSCAN.
# Each cluster is then labelled by gpt-4o-mini from 5 representative texts.

EMBED_MODEL = "text-embedding-3-small"


async def _embed_batch(client: AsyncOpenAI, texts: list[str]) -> list[list[float]]:
    r = await client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [e.embedding for e in r.data]


def _embed_all(texts: list[str], dataset_name: str) -> "np.ndarray":
    import numpy as np
    cache_p = CACHE_DIR / f"embeddings_{dataset_name}.parquet"
    cached: dict[str, list[float]] = {}
    if cache_p.exists():
        df = pd.read_parquet(cache_p)
        cached = {r["hash"]: list(r["embedding"]) for _, r in df.iterrows()}

    pending: list[tuple[int, str]] = []
    out_emb: list[list[float] | None] = [None] * len(texts)
    for i, t in enumerate(texts):
        h = hashlib.sha1(t.strip().encode("utf-8")).hexdigest()
        if h in cached:
            out_emb[i] = cached[h]
        else:
            pending.append((i, t))
    print(f"  embeddings: cached {len(texts) - len(pending)}/{len(texts)}, calling API for {len(pending)}")

    if pending:
        async def go():
            client = AsyncOpenAI()
            BATCH = 96
            for j in range(0, len(pending), BATCH):
                chunk = pending[j:j + BATCH]
                embs = await _embed_batch(client, [t[:8000] for _, t in chunk])
                for (orig_i, t), e in zip(chunk, embs):
                    out_emb[orig_i] = e
                    cached[hashlib.sha1(t.strip().encode("utf-8")).hexdigest()] = e
        asyncio.run(go())
        rows = [{"hash": h, "embedding": e} for h, e in cached.items()]
        pd.DataFrame(rows).to_parquet(cache_p, index=False)

    return np.array(out_emb, dtype="float32")


async def _label_clusters(samples_per_cluster: dict[int, list[str]]) -> dict[int, str]:
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    async def label_one(cid: int, samples: list[str]) -> tuple[int, str]:
        async with sem:
            txt = "\n".join(f"- {s[:300]}" for s in samples[:5])
            try:
                r = await client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "You produce SHORT (3-6 word) thematic labels for clusters of Nigerian masculinity-related social media text. Return STRICT JSON: {\"label\": \"...\"}"},
                        {"role": "user", "content": f"Sample posts in this cluster:\n{txt}\n\nReturn a 3-6 word descriptive label that captures the dominant theme."},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                )
                data = json.loads(r.choices[0].message.content)
                return cid, data.get("label", f"cluster_{cid}")
            except Exception:
                return cid, f"cluster_{cid}"

    out = await atqdm.gather(*[label_one(cid, samples) for cid, samples in samples_per_cluster.items()])
    return dict(out)


def cluster_topics(texts: list[str], dataset_name: str, min_cluster_size: int | None = None) -> pd.DataFrame:
    """
    Embed → UMAP → HDBSCAN → label. Returns DataFrame with columns:
      topic_cluster_id     (int; -1 means noise/no cluster)
      topic_cluster_label  (str)
    Aligned to input order.
    """
    import numpy as np
    import umap
    import hdbscan

    print(f"  clustering {len(texts)} texts ({dataset_name})...")
    embs = _embed_all(texts, dataset_name)

    n = len(texts)
    if n < 10:
        return pd.DataFrame({"topic_cluster_id": [-1] * n, "topic_cluster_label": ["unclustered"] * n})

    # UMAP to 5 dims
    n_neighbors = max(5, min(15, n - 1))
    reducer = umap.UMAP(n_components=5, n_neighbors=n_neighbors, min_dist=0.0, metric="cosine", random_state=42)
    reduced = reducer.fit_transform(embs)

    # HDBSCAN
    if min_cluster_size is None:
        min_cluster_size = max(5, int(n ** 0.5 / 2))
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean", cluster_selection_method="eom")
    labels = clusterer.fit_predict(reduced)

    print(f"  → {len(set(labels)) - (1 if -1 in labels else 0)} clusters, {(labels == -1).sum()} noise points")

    # Sample representatives per cluster (closest to centroid in reduced space)
    samples_per_cluster: dict[int, list[str]] = {}
    for cid in sorted(set(labels)):
        if cid == -1:
            continue
        idx = np.where(labels == cid)[0]
        centroid = reduced[idx].mean(axis=0)
        dists = np.linalg.norm(reduced[idx] - centroid, axis=1)
        order = idx[np.argsort(dists)]
        samples_per_cluster[cid] = [texts[i] for i in order[:5]]

    cluster_labels = asyncio.run(_label_clusters(samples_per_cluster)) if samples_per_cluster else {}
    cluster_labels[-1] = "noise/unclustered"

    return pd.DataFrame({
        "topic_cluster_id": labels,
        "topic_cluster_label": [cluster_labels.get(int(c), f"cluster_{c}") for c in labels],
    })
