"""Build 'Audience Demo Comments.ipynb' — focused topic-relevance filter for the
two finalized regressive Nigeria posts (Agba John Doe + Shola).

Goal: ~400 scope-relevant comments total (~200 per post), every comment
substantive (>7 stripped words), filtering that is lenient on topic match
but strict on substance.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NB_PATH = ROOT / "Notebooks" / "Audience Demo Comments.ipynb"


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text.splitlines(keepends=True),
    }


CELLS = []

# -------------------------------------------------------------------
CELLS.append(md("""# Audience Demo Comments — Nigeria Regressive

**Norman Lear Center × Gates Foundation — Manfluencer project**

Focused topic-relevance filter over the two **finalized** regressive Nigeria posts:

| Creator | Post | Raw |
|---|---|---|
| Agba John Doe | Never Leave Marriage Because Husband Cheated | 511 |
| Shola | 7 Women Will Beg One Man to Marry | 454 |

## Goal
Produce **~400 scope-relevant comments total** (≈200 per post) for the audience demo.

## Filtering rules
1. **Substance gate** — comment must have **more than 7 words** after stripping URLs / mentions / emojis.
2. **Keyword annotation** — NLC Nigeria lexicon (signal, not gate).
3. **Semantic similarity** — `text-embedding-3-large` cosine to scope-anchor phrases (regressive-leaning + general manosphere themes).
4. **LLM relevance** — `gpt-4o-mini` lenient binary judgment: does the comment meaningfully engage with the post's topic (gender norms, marriage, infidelity, polygamy, female agency, male/female dynamics)? Agreement, pushback, testimony, advice, lived-experience, religion-framed takes — all relevant. `:eyes:`-only / spam / pure praise → not relevant.
5. **Composite score** — weighted blend; top-200 per post.

## Output
`Audience Demo Comments/<Creator>/<Post>.xlsx` — one column `text` plus the per-post summary in `_summary.xlsx`.
"""))

# -------------------------------------------------------------------
CELLS.append(md("## 0 — Setup"))

CELLS.append(code("""from __future__ import annotations

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

ROOT = Path.cwd().parent if Path.cwd().name == "Notebooks" else Path.cwd()
print("Project root:", ROOT)
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY not set — add it to .env"
print("OpenAI key loaded:", os.getenv("OPENAI_API_KEY")[:8] + "…")
"""))

# -------------------------------------------------------------------
CELLS.append(md("## 1 — Config"))

CELLS.append(code("""INPUT_DIR = ROOT / "Nigeria Audience Comments"
KEYWORDS_XLSX = ROOT / "Codebook and Keywords" / "NLC Proposed keywords.xlsx"
OUTPUT_DIR = ROOT / "Audience Demo Comments"
TEMP_DIR = ROOT / "temp" / "audience_demo_comments"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EMBEDDING_MODEL = "text-embedding-3-large"
LLM_MODEL = "gpt-4o-mini"

MIN_WORDS = 8                  # >7 words required (stripped)
TARGET_PER_POST = 200          # ~400 total across the two posts
LLM_BATCH_SIZE = 20
LLM_CONCURRENCY = 16
EMBED_BATCH_SIZE = 256

SELECTED_POSTS = [
    {
        "creator": "Agba John Doe",
        "orientation": "Regressive",
        "post": "Never Leave Marriage Because Husband Cheated",
        "file": "Never Leave Marriage Because Husband Cheated.xlsx",
        "text_col": "text",
        "creator_handle": "jon_d_doe",
    },
    {
        "creator": "Shola",
        "orientation": "Regressive",
        "post": "7 Women Will Beg One Man to Marry",
        "file": "7 Women Will Beg One Man to Marry.xlsx",
        "text_col": "text",
        "creator_handle": "itsSh0la",
    },
]

for p in SELECTED_POSTS:
    print(f"  • {p['creator']:<18} [{p['orientation']}] {p['post']}")
"""))

# -------------------------------------------------------------------
CELLS.append(md("""## 2 — Load raw comments

Drops the OP's own thread continuations and any pull-quote replies that just paraphrase the post.
"""))

CELLS.append(code("""def _normalize_text(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\\u201c", '"').replace("\\u201d", '"')
    s = s.replace("\\u2018", "'").replace("\\u2019", "'")
    s = re.sub(r"\\s+", " ", s).strip()
    return s


def _strip_leading_handle(text, handle):
    if not handle or not isinstance(text, str):
        return text
    pattern = re.compile(rf"^\\s*@{re.escape(handle)}\\b[\\s:,.-]*", flags=re.IGNORECASE)
    return pattern.sub("", text).strip()


def _norm_for_ngram(t):
    t = str(t).lower()
    t = re.sub(r"[^a-z0-9\\s]", " ", t)
    return re.sub(r"\\s+", " ", t).strip()


def _ngrams(t, n=8):
    toks = t.split()
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)} if len(toks) >= n else {t}


def load_post(meta):
    path = INPUT_DIR / meta["creator"] / meta["file"]
    df = pd.read_excel(path)
    handle = meta.get("creator_handle")

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

    print(f"  · {meta['creator']:<18} {meta['post'][:42]}: "
          f"{len(df):>4} rows  (dropped {dropped_op} OP, {dropped_quotes} quotes)")
    return df[keep_cols]


raw_frames = [load_post(p) for p in SELECTED_POSTS]
raw = pd.concat(raw_frames, ignore_index=True)
print(f"\\nTotal raw rows after OP / quote removal: {len(raw):,}")
raw.groupby(['creator', 'post']).size()
"""))

# -------------------------------------------------------------------
CELLS.append(md("""## 3 — Substance gate (> 7 words)

Strip URLs, mentions, emojis, hashtags. Require **more than 7 alphabetic words** so we never select a one-liner reaction. Keeps the bar tight on substance while leaving topic match to later stages.
"""))

CELLS.append(code("""EMOJI_PATTERN = re.compile(
    "[\\U0001F300-\\U0001FAFF\\U0001F600-\\U0001F64F\\U0001F680-\\U0001F6FF"
    "\\U00002600-\\U000027BF\\U0001F900-\\U0001F9FF\\U00002700-\\U000027BF"
    "\\U0001F100-\\U0001F1FF]+",
    flags=re.UNICODE,
)
URL_PATTERN = re.compile(r"https?://\\S+|www\\.\\S+|\\S+\\.(com|co|ng|org|io)/\\S*", flags=re.IGNORECASE)
MENTION_PATTERN = re.compile(r"@\\w+")


def strip_decorations(s):
    s = URL_PATTERN.sub(" ", s)
    s = MENTION_PATTERN.sub(" ", s)
    s = EMOJI_PATTERN.sub(" ", s)
    s = re.sub(r"\\s+", " ", s).strip()
    return s


def quality_signals(text):
    stripped = strip_decorations(text)
    words = re.findall(r"[A-Za-z']+", stripped)
    n_words = len(words)
    longest = max((len(w) for w in words), default=0)
    return pd.Series({
        "stripped_text": stripped,
        "n_words": n_words,
        "longest_word_len": longest,
    })


signals = raw["raw_text"].apply(quality_signals)
df = pd.concat([raw, signals], axis=1)

df["is_substantive"] = (df["n_words"] >= MIN_WORDS) & (df["longest_word_len"] >= 3)

retention = (df.groupby(["creator", "post"])
               .agg(raw=("raw_text", "count"), substantive=("is_substantive", "sum"))
               .reset_index())
retention["retention_rate"] = retention["substantive"] / retention["raw"]
print(f"Substantive (>{MIN_WORDS - 1} words): {int(df['is_substantive'].sum()):,} / {len(df):,} "
      f"({df['is_substantive'].mean():.1%})")
retention
"""))

# -------------------------------------------------------------------
CELLS.append(md("""## 4 — Keyword annotation (NLC Nigeria lexicon)

Loose signal — we don't drop comments without a keyword, just reward those that have one.
"""))

CELLS.append(code("""kw_df = pd.read_excel(KEYWORDS_XLSX, sheet_name="Nigeria")
kw_df = kw_df.dropna(subset=["Keyword"])
kw_df["Keyword"] = kw_df["Keyword"].astype(str).str.strip()
kw_df = kw_df[kw_df["Keyword"].str.len() >= 2]

rel_col = "Relevance to manosphere conversations"
kw_highly = set(kw_df.loc[kw_df[rel_col].str.contains("Highly", na=False), "Keyword"].str.lower())
kw_moderate = set(kw_df.loc[kw_df[rel_col].str.contains("Moderately", na=False), "Keyword"].str.lower())
all_kws = sorted(kw_highly | kw_moderate, key=len, reverse=True)
print(f"Lexicon: {len(kw_df)} terms — {len(kw_highly)} highly, {len(kw_moderate)} moderately relevant")

escaped = [re.escape(k) for k in all_kws]
kw_regex = re.compile(r"\\b(" + "|".join(escaped) + r")\\b", flags=re.IGNORECASE) if escaped else None


def kw_hits(text):
    if not kw_regex or not text:
        return []
    return list(dict.fromkeys(kw_regex.findall(text.lower())))


df["keyword_hits"] = df["raw_text"].apply(kw_hits)
df["has_keyword"] = df["keyword_hits"].str.len() > 0
df["n_keyword_hits"] = df["keyword_hits"].str.len()

kw_summary = (df[df["is_substantive"]]
              .groupby(["creator", "post"])
              .agg(substantive=("is_substantive", "sum"),
                   with_keyword=("has_keyword", "sum"))
              .reset_index())
kw_summary["keyword_rate"] = kw_summary["with_keyword"] / kw_summary["substantive"]
kw_summary
"""))

# -------------------------------------------------------------------
CELLS.append(md("""## 5 — Semantic relevance (OpenAI embeddings)

Anchor phrases cover the regressive Nigeria masculinity discourse: marriage / infidelity / polygamy / female-scarcity narratives, traditional gender roles, religious framing of marriage, plus general agreement / pushback so engaged short reactions still score.
"""))

CELLS.append(code("""ANCHORS = [
    # Core masculinity & gender roles
    "views on what it means to be a man",
    "traditional gender roles and male provider expectations",
    "female submission, obedience and the role of a wife",
    "men as the prize and women competing for husbands",
    # Marriage, infidelity, polygamy
    "marriage, infidelity and whether to leave a cheating husband",
    "polygamy and female scarcity narratives",
    "divorce, second-hand wives and the marriage market",
    "advice to married women about staying or leaving",
    # Religion-framed
    "biblical or religious framing of marriage and gender",
    "faith, partnership and trust in marriage",
    # Reactions / engagement
    "agreement with the creator's regressive take on women or marriage",
    "disagreement or feminist pushback against the creator",
    "personal testimony from a man or woman about marriage and relationships",
    "advice to young men or young women about love and marriage",
    # Adjacent manosphere themes
    "feminism, misogyny and women's rights",
    "men's responsibilities, accountability and male behaviour",
    "sex, dating standards and sexual double standards",
]

client = OpenAI()


def embed_batch(texts, model=EMBEDDING_MODEL):
    resp = client.embeddings.create(model=model, input=list(texts))
    return np.array([d.embedding for d in resp.data])


anchor_emb = embed_batch(ANCHORS)
anchor_emb = anchor_emb / np.linalg.norm(anchor_emb, axis=1, keepdims=True)
print("Anchor embeddings:", anchor_emb.shape)
"""))

CELLS.append(code("""sub = df[df["is_substantive"]].copy().reset_index(drop=True)

embeds_path = TEMP_DIR / "comment_embeddings.npy"
if embeds_path.exists() and len(np.load(embeds_path)) == len(sub):
    emb = np.load(embeds_path)
    print(f"Loaded cached embeddings: {emb.shape}")
else:
    emb_list = []
    for start in tqdm(range(0, len(sub), EMBED_BATCH_SIZE), desc="embedding"):
        chunk = sub["stripped_text"].iloc[start:start + EMBED_BATCH_SIZE].tolist()
        emb_list.append(embed_batch(chunk))
    emb = np.vstack(emb_list)
    np.save(embeds_path, emb)
    print("Embeddings:", emb.shape)

emb_norm = emb / np.linalg.norm(emb, axis=1, keepdims=True)
sim = emb_norm @ anchor_emb.T
sub["sim_max"] = sim.max(axis=1)
sub["sim_top_anchor"] = [ANCHORS[i] for i in sim.argmax(axis=1)]
sub[["creator", "post", "stripped_text", "sim_max", "sim_top_anchor"]].head()
"""))

# -------------------------------------------------------------------
CELLS.append(md("""## 6 — LLM relevance (GPT-4o-mini, lenient)

Each substantive comment goes to `gpt-4o-mini` in batches of 20. The prompt is **lenient on topic match** — agreement, pushback, lived-experience testimony, advice, religious takes are all `relevant`. Only pure spam, hype, off-topic chatter, and personal attacks-with-no-substance are rejected.
"""))

CELLS.append(code("""SYSTEM_PROMPT = '''You are a research coder reviewing audience comments on Nigerian social-media posts by REGRESSIVE male-influencers (themes: women should not leave cheating husbands; men are the prize; female scarcity; submission; biblical framing of marriage).

Mark a comment RELEVANT if it engages — in any way — with the post's themes. Be GENEROUS:
  • Direct discussion of marriage, infidelity, polygamy, gender roles, female agency, sex, dating standards, masculinity, religion's view on marriage.
  • Agreement OR disagreement with the creator's regressive position.
  • Personal testimony / lived experience about marriage, relationships, family, men/women.
  • Advice to men or to women about love, marriage, or partnership.
  • Religion- or culture-framed takes on gender ("the bible said…", "in our culture…").
  • Substantive reaction with a reason ("this is true because…", "I disagree because…").

Mark NOT RELEVANT only if:
  • Pure spam, ads, promotional links.
  • Off-topic chatter (sports, news, the creator's looks, "follow me back").
  • Empty hype with zero content ("nice one", "lmao", "first").
  • Pure insult of the creator with no engagement on the topic.

Return a JSON object with key "results" whose value is a list of:
  {"id": <int>, "relevant": true|false, "reason": "<short reason, 12 words max>"}.
Output nothing else.'''


def build_user_prompt(post_title, batch):
    lines = [f"Post: {post_title}", "", "Comments:"]
    for i, text in batch:
        safe = text.replace("\\n", " ")[:400]
        lines.append(f"[{i}] {safe}")
    return "\\n".join(lines)


async_client = AsyncOpenAI()


async def classify_batch(local_to_global, batch, post_title, sem):
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


async def classify_all(sub_df):
    sem = asyncio.Semaphore(LLM_CONCURRENCY)
    coroutines = []
    for (creator, post), g in sub_df.groupby(["creator", "post"]):
        g_idx = g.index.tolist()
        texts = g["stripped_text"].tolist()
        for start in range(0, len(texts), LLM_BATCH_SIZE):
            chunk_local = list(enumerate(texts[start:start + LLM_BATCH_SIZE], start=start))
            local_to_global = {local_i: g_idx[local_i] for local_i, _ in chunk_local}
            coroutines.append(classify_batch(local_to_global, chunk_local, post, sem))

    print(f"Dispatching {len(coroutines)} LLM batches × up to {LLM_BATCH_SIZE} comments "
          f"({LLM_CONCURRENCY} concurrent)")
    all_rows = []
    tasks = [asyncio.create_task(c) for c in coroutines]
    for fut in atqdm.as_completed(tasks, total=len(tasks), desc="LLM"):
        rows = await fut
        all_rows.extend(rows)
    return all_rows


llm_results_path = TEMP_DIR / "llm_results.parquet"
if llm_results_path.exists():
    llm_df = pd.read_parquet(llm_results_path)
    print(f"Loaded cached LLM results: {len(llm_df):,}")
else:
    all_rows = await classify_all(sub)
    llm_df = pd.DataFrame(
        [{"sub_idx": idx, "llm_relevant": rel, "llm_reason": reason}
         for idx, rel, reason in all_rows]
    ).drop_duplicates("sub_idx")
    llm_df.to_parquet(llm_results_path)
    print(f"LLM classifications: {len(llm_df):,}")

sub = sub.merge(llm_df, left_index=True, right_on="sub_idx", how="left").drop(columns="sub_idx").reset_index(drop=True)
sub["llm_relevant"] = sub["llm_relevant"].fillna(False).astype(bool)
print(f"LLM-relevant rate: {sub['llm_relevant'].mean():.1%}")

llm_summary = (sub.groupby(["creator", "post"])
                .agg(substantive=("llm_relevant", "size"),
                     llm_relevant=("llm_relevant", "sum"))
                .reset_index())
llm_summary["llm_rate"] = llm_summary["llm_relevant"] / llm_summary["substantive"]
llm_summary
"""))

# -------------------------------------------------------------------
CELLS.append(md("""## 7 — Composite scoring + top-200 selection per post

`score = 0.20 * has_keyword + 0.35 * sim_max_scaled + 0.45 * llm_relevant`

LLM relevance is the dominant signal; embedding similarity ranks within the LLM-relevant pool; keyword hits nudge culturally-specific masculinity vocabulary. We take the top **200 per post → ~400 total**, drawing from `llm_relevant=True` first; if a post has fewer than 200 LLM-relevant we fall back to the broader pool.
"""))

CELLS.append(code("""sub["sim_scaled"] = sub.groupby("post")["sim_max"].transform(
    lambda s: (s - s.min()) / (s.max() - s.min() + 1e-9)
)
sub["score"] = (
    0.20 * sub["has_keyword"].astype(float)
    + 0.35 * sub["sim_scaled"]
    + 0.45 * sub["llm_relevant"].astype(float)
)

selected_frames = []
for (creator, post), g in sub.groupby(["creator", "post"]):
    # Hard gate: only LLM-relevant comments are eligible. If a post has fewer than
    # TARGET_PER_POST LLM-relevant comments, we take all of them (correctness > quota).
    eligible = g[g["llm_relevant"]].copy().sort_values("score", ascending=False)
    top = eligible.head(TARGET_PER_POST).copy()
    top["rank"] = range(1, len(top) + 1)
    selected_frames.append(top)

selected = pd.concat(selected_frames, ignore_index=True)

selection_summary = (selected.groupby(["creator", "post"])
                     .agg(selected=("rank", "size"),
                          avg_score=("score", "mean"),
                          avg_words=("n_words", "mean"),
                          avg_sim=("sim_max", "mean"),
                          kw_rate=("has_keyword", "mean"),
                          llm_rate=("llm_relevant", "mean"))
                     .reset_index())
print(f"Selected {len(selected):,} comments total")
selection_summary
"""))

# -------------------------------------------------------------------
CELLS.append(md("""## 8 — Export to `Audience Demo Comments/`"""))

CELLS.append(code("""def _safe(name):
    return re.sub(r"[^\\w\\- ]+", "", name).strip()


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

summary = pd.DataFrame(summary_rows)
summary_path = OUTPUT_DIR / "_summary.xlsx"
summary.to_excel(summary_path, index=False)
print(f"Wrote {len(summary)} files to {OUTPUT_DIR}")
print(f"Total comments exported: {summary['rows'].sum():,}")
summary
"""))

# -------------------------------------------------------------------
CELLS.append(md("## 9 — Sanity check"))

CELLS.append(code("""# Verify every exported comment has > 7 words and is on-topic.
for row in summary_rows:
    out = pd.read_excel(ROOT / row["path"])
    word_counts = out["text"].apply(lambda t: len(re.findall(r"[A-Za-z']+", strip_decorations(str(t)))))
    print(f"{row['creator']:<18} {row['post'][:42]:<42}  n={len(out):>3}  "
          f"min_words={word_counts.min():>2}  median={int(word_counts.median()):>3}  max={word_counts.max():>3}")
    assert word_counts.min() >= MIN_WORDS, f"Found comment with < {MIN_WORDS} words!"

print("\\nAll exported comments satisfy >7 word requirement.")
"""))

# -------------------------------------------------------------------
nb = {
    "cells": CELLS,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.10"},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

NB_PATH.parent.mkdir(parents=True, exist_ok=True)
NB_PATH.write_text(json.dumps(nb, indent=1))
print(f"Wrote {NB_PATH.relative_to(ROOT)} ({len(CELLS)} cells)")
