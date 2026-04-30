"""Audience Demo — Deyemi Okanlawon (Nigeria progressive).

Same pipeline as `build_audience_demo_notebook.py` (Agba John Doe + Shola),
but tuned for the progressive creator:

  1. OP / quote-paraphrase removal
  2. Substance gate (>7 stripped words)
  3. Keyword annotation (NLC Nigeria lexicon — signal not gate)
  4. Embedding similarity to PROGRESSIVE-themed anchors
  5. Lenient LLM relevance with PROGRESSIVE-themed prompt
  6. Composite score: 0.20*kw + 0.35*sim + 0.45*llm
  7. Top-200 LLM-relevant per post (or all of them if < 200 available)
  8. Output `Audience Demo Comments/Deyemi Okanlawon/<Post>.xlsx` with one
     column `text`. Update `Audience Demo Comments/_summary.xlsx`.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI
from tqdm.asyncio import tqdm as atqdm
from tqdm.auto import tqdm


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

INPUT_DIR = ROOT / "Nigeria Audience Comments"
KEYWORDS_XLSX = ROOT / "Codebook and Keywords" / "NLC Proposed keywords.xlsx"
OUTPUT_DIR = ROOT / "Audience Demo Comments"
TEMP_DIR = ROOT / "temp" / "audience_demo_comments"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EMBEDDING_MODEL = "text-embedding-3-large"
LLM_MODEL = "gpt-4o-mini"

MIN_WORDS = 8                # >7 words required (stripped)
TARGET_PER_POST = 200
LLM_BATCH_SIZE = 20
LLM_CONCURRENCY = 16
EMBED_BATCH_SIZE = 256

SELECTED_POSTS = [
    {
        "creator": "Deyemi Okanlawon",
        "orientation": "Progressive",
        "post": "Stop Raping Women Response",
        "file": "Stop Raping Women Response.xlsx",
        "text_col": "text",
        "creator_handle": "_deyemi",
    },
    {
        "creator": "Deyemi Okanlawon",
        "orientation": "Progressive",
        "post": "Tweet Replies Pooled",
        "file": "Tweet Replies Pooled.xlsx",
        "text_col": "text",
        "creator_handle": "_deyemi",
    },
]

# Progressive-themed anchors (Deyemi: anti-rape advocacy, male accountability,
# boy-child / male-victim discourse, gender-debate, false-accusation framing).
ANCHORS = [
    "men holding men accountable for sexual violence and rape",
    "stop raping women — anti rape advocacy by male voices",
    "men supporting women's safety and bodily autonomy",
    "false rape accusations vs legitimate accusations and due process",
    "boy-child protection and men as victims of sexual abuse",
    "male defensiveness, whataboutism and 'not all men' deflection",
    "feminist pushback and gender-debate on social media",
    "biblical or religious framing of justice, mercy and accountability",
    "personal testimony from a man or woman about sexual violence or harassment",
    "what makes a real man — accountability, respect and integrity",
    "male emotional vulnerability, mental health and lived experience",
    "Simi backlash, parental responsibility and child safety online",
    "male behaviour, masculinity norms and gendered double standards",
    "advice to men about respecting women and rejecting rape culture",
    "agreement with the creator's progressive position on rape and accountability",
    "disagreement, hostility or backlash against the creator's progressive take",
]

# Progressive LLM prompt (lenient on topic match, strict on substance).
SYSTEM_PROMPT = """You are a research coder reviewing audience comments on Nigerian social-media posts by a PROGRESSIVE male public figure (Deyemi Okanlawon). His themes: stop raping women; men must hold men accountable for sexual violence; anti-rape advocacy; pushback against male defensiveness, false-accusation deflection, and whataboutism; gender debate; male responsibility.

Mark a comment RELEVANT if it engages — in any way — with the post's themes. Be GENEROUS:
  • Direct discussion of rape, sexual violence, gender-based violence, false accusations, due process, men's accountability, women's safety.
  • Boy-child / male-victim framing, "what about boys/men?" deflection, calls for protecting men from false accusations.
  • Discussion of masculinity, what real men should do, gender roles in marriage / family.
  • Feminist support OR anti-feminist pushback against the creator's position.
  • Personal testimony / lived experience about sexual violence, harassment, abuse, false accusations.
  • Religion- or culture-framed takes on justice, mercy, accountability ("the bible said…", "in our culture…").
  • Substantive reaction with a reason ("this is true because…", "I disagree because…").
  • Simi-related backlash about predator/child-safety claims (this is a major sub-thread on these posts).

Mark NOT RELEVANT only if:
  • Pure spam, ads, promotional links, follow-back requests.
  • Off-topic chatter (sports, an unrelated political case, the creator's looks).
  • Empty hype with zero content ("nice one", "lmao", "first", "preach").
  • Pure insult of the creator with no engagement on the topic.

Return a JSON object with key "results" whose value is a list of:
  {"id": <int>, "relevant": true|false, "reason": "<short reason, 12 words max>"}.
Output nothing else."""


# ---------------------------------------------------------------------------
# 1. Load & clean
# ---------------------------------------------------------------------------
def _normalize_text(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_leading_handle(text, handle):
    if not handle or not isinstance(text, str):
        return text
    pattern = re.compile(rf"^\s*@{re.escape(handle)}\b[\s:,.\-]*", flags=re.IGNORECASE)
    return pattern.sub("", text).strip()


def _strip_parent_tweet(text):
    """Tweet Replies Pooled.xlsx prepends 'PARENT TWEET (Deyemi): "..." || REPLY: ...'.
    Keep only the reply part for analysis."""
    s = str(text)
    m = re.search(r"\|\|\s*REPLY:\s*", s)
    if m:
        return s[m.end():].strip()
    return s


def _norm_for_ngram(t):
    t = str(t).lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _ngrams(t, n=8):
    toks = t.split()
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)} if len(toks) >= n else {t}


def load_post(meta):
    path = INPUT_DIR / meta["creator"] / meta["file"]
    df = pd.read_excel(path)
    handle = meta.get("creator_handle")

    # Strip parent tweet for the pooled-replies file
    if "Tweet Replies Pooled" in meta["post"]:
        df[meta["text_col"]] = df[meta["text_col"]].apply(_strip_parent_tweet)

    dropped_op = 0
    op_ngrams = set()
    if handle and "author" in df.columns:
        mask = df["author"].astype(str).str.lower() == handle.lower()
        dropped_op = int(mask.sum())
        for t in df.loc[mask, meta["text_col"]].astype(str):
            op_ngrams |= _ngrams(_norm_for_ngram(t))
        df = df.loc[~mask].reset_index(drop=True)

    df["raw_text"] = df[meta["text_col"]].apply(_normalize_text)
    if handle:
        df["raw_text"] = df["raw_text"].apply(lambda t: _strip_leading_handle(t, handle))

    dropped_quotes = 0
    if op_ngrams:
        def is_quote(t):
            ng = _ngrams(_norm_for_ngram(t))
            if not ng:
                return False
            overlap = len(ng & op_ngrams) / len(ng)
            return overlap >= 0.5 and len(_norm_for_ngram(t).split()) >= 8
        quote_mask = df["raw_text"].apply(is_quote)
        dropped_quotes = int(quote_mask.sum())
        df = df.loc[~quote_mask].reset_index(drop=True)

    df["creator"] = meta["creator"]
    df["orientation"] = meta["orientation"]
    df["post"] = meta["post"]
    keep_cols = ["creator", "orientation", "post", "raw_text"]
    for aux in ("author", "likes", "replies", "retweets", "timestamp", "url"):
        if aux in df.columns:
            keep_cols.append(aux)

    print(f"  · {meta['creator']:<18} {meta['post'][:42]:<42}: "
          f"{len(df):>4} rows  (dropped {dropped_op} OP, {dropped_quotes} quotes)")
    return df[keep_cols]


# ---------------------------------------------------------------------------
# 2. Substance gate
# ---------------------------------------------------------------------------
EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U00002600-\U000027BF\U0001F900-\U0001F9FF\U00002700-\U000027BF"
    "\U0001F100-\U0001F1FF]+",
    flags=re.UNICODE,
)
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+|\S+\.(com|co|ng|org|io)/\S*", flags=re.IGNORECASE)
MENTION_PATTERN = re.compile(r"@\w+")


def strip_decorations(s):
    s = URL_PATTERN.sub(" ", s)
    s = MENTION_PATTERN.sub(" ", s)
    s = EMOJI_PATTERN.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def quality_signals(text):
    stripped = strip_decorations(text)
    words = re.findall(r"[A-Za-z']+", stripped)
    return pd.Series({
        "stripped_text": stripped,
        "n_words": len(words),
        "longest_word_len": max((len(w) for w in words), default=0),
    })


# ---------------------------------------------------------------------------
# 3. Embeddings
# ---------------------------------------------------------------------------
def embed_batch(client, texts, model=EMBEDDING_MODEL):
    resp = client.embeddings.create(model=model, input=list(texts))
    return np.array([d.embedding for d in resp.data])


# ---------------------------------------------------------------------------
# 4. LLM relevance
# ---------------------------------------------------------------------------
def build_user_prompt(post_title, batch):
    lines = [f"Post: {post_title}", "", "Comments:"]
    for i, text in batch:
        safe = text.replace("\n", " ")[:400]
        lines.append(f"[{i}] {safe}")
    return "\n".join(lines)


async def classify_batch(async_client, local_to_global, batch, post_title, sem):
    async with sem:
        for attempt in range(4):
            try:
                resp = await async_client.chat.completions.create(
                    model=LLM_MODEL,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_prompt(post_title, batch)},
                    ],
                )
                data = json.loads(resp.choices[0].message.content)
                items = data.get("results", [])
                out = []
                for r in items:
                    lid = r.get("id")
                    if lid in local_to_global:
                        out.append((local_to_global[lid], bool(r.get("relevant")), r.get("reason", "")))
                return out
            except Exception as e:
                if attempt == 3:
                    print(f"  LLM batch failed after 4 tries: {e}")
                    return [(local_to_global[i], None, f"error: {e}") for i, _ in batch]
                await asyncio.sleep(2 ** attempt)


async def classify_all(async_client, sub_df):
    sem = asyncio.Semaphore(LLM_CONCURRENCY)
    coroutines = []
    for (creator, post), g in sub_df.groupby(["creator", "post"]):
        g_idx = g.index.tolist()
        texts = g["stripped_text"].tolist()
        for start in range(0, len(texts), LLM_BATCH_SIZE):
            chunk_local = list(enumerate(texts[start:start + LLM_BATCH_SIZE], start=start))
            local_to_global = {local_i: g_idx[local_i] for local_i, _ in chunk_local}
            coroutines.append(classify_batch(async_client, local_to_global, chunk_local, post, sem))

    print(f"Dispatching {len(coroutines)} LLM batches × up to {LLM_BATCH_SIZE} comments "
          f"({LLM_CONCURRENCY} concurrent)")
    all_rows = []
    tasks = [asyncio.create_task(c) for c in coroutines]
    for fut in atqdm.as_completed(tasks, total=len(tasks), desc="LLM"):
        rows = await fut
        all_rows.extend(rows)
    return all_rows


# ---------------------------------------------------------------------------
# 5. Pipeline
# ---------------------------------------------------------------------------
def _safe(name):
    return re.sub(r"[^\w\- ]+", "", name).strip()


async def main_async():
    # Load
    print("=== 1. Load ===")
    raw_frames = [load_post(p) for p in SELECTED_POSTS]
    raw = pd.concat(raw_frames, ignore_index=True)
    print(f"\nTotal raw rows after OP / quote removal: {len(raw):,}")

    # Substance
    print("\n=== 2. Substance gate ===")
    signals = raw["raw_text"].apply(quality_signals)
    df = pd.concat([raw, signals], axis=1)
    df["is_substantive"] = (df["n_words"] >= MIN_WORDS) & (df["longest_word_len"] >= 3)
    print(f"Substantive (>{MIN_WORDS - 1} words): {int(df['is_substantive'].sum()):,} / {len(df):,} "
          f"({df['is_substantive'].mean():.1%})")

    # Keyword annotation
    print("\n=== 3. Keyword annotation ===")
    kw_df = pd.read_excel(KEYWORDS_XLSX, sheet_name="Nigeria")
    kw_df = kw_df.dropna(subset=["Keyword"])
    kw_df["Keyword"] = kw_df["Keyword"].astype(str).str.strip()
    kw_df = kw_df[kw_df["Keyword"].str.len() >= 2]
    rel_col = "Relevance to manosphere conversations"
    kw_highly = set(kw_df.loc[kw_df[rel_col].str.contains("Highly", na=False), "Keyword"].str.lower())
    kw_moderate = set(kw_df.loc[kw_df[rel_col].str.contains("Moderately", na=False), "Keyword"].str.lower())
    all_kws = sorted(kw_highly | kw_moderate, key=len, reverse=True)
    escaped = [re.escape(k) for k in all_kws]
    kw_regex = re.compile(r"\b(" + "|".join(escaped) + r")\b", flags=re.IGNORECASE) if escaped else None

    def kw_hits(text):
        if not kw_regex or not text:
            return []
        return list(dict.fromkeys(kw_regex.findall(text.lower())))

    df["keyword_hits"] = df["raw_text"].apply(kw_hits)
    df["has_keyword"] = df["keyword_hits"].str.len() > 0
    print(f"With keyword: {int((df['is_substantive'] & df['has_keyword']).sum())} of "
          f"{int(df['is_substantive'].sum())} substantive")

    # Embeddings
    print("\n=== 4. Embeddings ===")
    sub = df[df["is_substantive"]].copy().reset_index(drop=True)
    client = OpenAI()
    anchor_emb = embed_batch(client, ANCHORS)
    anchor_emb = anchor_emb / np.linalg.norm(anchor_emb, axis=1, keepdims=True)

    embeds_path = TEMP_DIR / "deyemi_comment_embeddings.npy"
    if embeds_path.exists() and len(np.load(embeds_path)) == len(sub):
        emb = np.load(embeds_path)
        print(f"Loaded cached embeddings: {emb.shape}")
    else:
        emb_list = []
        for start in tqdm(range(0, len(sub), EMBED_BATCH_SIZE), desc="embedding"):
            chunk = sub["stripped_text"].iloc[start:start + EMBED_BATCH_SIZE].tolist()
            emb_list.append(embed_batch(client, chunk))
        emb = np.vstack(emb_list)
        np.save(embeds_path, emb)
        print(f"Embeddings: {emb.shape}")

    emb_norm = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    sim = emb_norm @ anchor_emb.T
    sub["sim_max"] = sim.max(axis=1)
    sub["sim_top_anchor"] = [ANCHORS[i] for i in sim.argmax(axis=1)]

    # LLM
    print("\n=== 5. LLM relevance ===")
    llm_results_path = TEMP_DIR / "deyemi_llm_results.parquet"
    if llm_results_path.exists():
        llm_df = pd.read_parquet(llm_results_path)
        print(f"Loaded cached LLM results: {len(llm_df):,}")
    else:
        async_client = AsyncOpenAI()
        all_rows = await classify_all(async_client, sub)
        llm_df = pd.DataFrame(
            [{"sub_idx": idx, "llm_relevant": rel, "llm_reason": reason}
             for idx, rel, reason in all_rows]
        ).drop_duplicates("sub_idx")
        llm_df.to_parquet(llm_results_path)
        print(f"LLM classifications: {len(llm_df):,}")

    sub = sub.merge(llm_df, left_index=True, right_on="sub_idx", how="left").drop(columns="sub_idx").reset_index(drop=True)
    sub["llm_relevant"] = sub["llm_relevant"].fillna(False).astype(bool)
    print(f"LLM-relevant rate: {sub['llm_relevant'].mean():.1%}")

    # Composite score + selection
    print("\n=== 6. Composite + top-N ===")
    sub["sim_scaled"] = sub.groupby("post")["sim_max"].transform(
        lambda s: (s - s.min()) / (s.max() - s.min() + 1e-9)
    )
    sub["score"] = (
        0.20 * sub["has_keyword"].astype(float)
        + 0.35 * sub["sim_scaled"]
        + 0.45 * sub["llm_relevant"].astype(float)
    )

    selected_frames = []
    for (creator, post), g in sub.groupby(["creator", "post"]):
        eligible = g[g["llm_relevant"]].copy().sort_values("score", ascending=False)
        top = eligible.head(TARGET_PER_POST).copy()
        top["rank"] = range(1, len(top) + 1)
        selected_frames.append(top)
    selected = pd.concat(selected_frames, ignore_index=True)
    print(f"Selected: {len(selected)} comments")

    # Export
    print("\n=== 7. Export ===")
    summary_rows = []
    for (creator, post), g in selected.groupby(["creator", "post"]):
        creator_dir = OUTPUT_DIR / _safe(creator)
        creator_dir.mkdir(parents=True, exist_ok=True)
        out_path = creator_dir / f"{_safe(post)}.xlsx"
        out = pd.DataFrame({"text": g.sort_values("rank")["raw_text"].values})
        out.to_excel(out_path, index=False)
        summary_rows.append({
            "creator": creator,
            "post": post,
            "rows": len(out),
            "path": str(out_path.relative_to(ROOT)),
        })
        print(f"  wrote {out_path.relative_to(ROOT)}: {len(out)}")

    # Update _summary.xlsx (preserve existing John Doe / Shola rows)
    summary_path = OUTPUT_DIR / "_summary.xlsx"
    if summary_path.exists():
        existing = pd.read_excel(summary_path)
        existing = existing[existing["creator"] != "Deyemi Okanlawon"]
        merged = pd.concat([existing, pd.DataFrame(summary_rows)], ignore_index=True)
    else:
        merged = pd.DataFrame(summary_rows)
    merged.to_excel(summary_path, index=False)

    total = sum(r["rows"] for r in summary_rows)
    print(f"\nDeyemi total scope-relevant: {total}")
    print(f"Updated {summary_path.relative_to(ROOT)}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
