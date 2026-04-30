"""Audience Demo — Banky Wellington MENtality (Nigeria progressive).

Same pipeline as `build_audience_demo_deyemi.py`, retuned for Banky's healthy-
masculinity / MENtality podcast framing. Sources: 6 MENtality episodes about
masculinity & money, relationships, fatherhood, friendship, young boys, and
relationships pt 2. Outputs one xlsx per episode in
`Audience Demo Comments/Banky Wellington/<Episode>.xlsx`, single `text` column.

Faith content is stripped at the end, matching the rest of the audience demo set.
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

INPUT_DIR = ROOT / "Nigeria Audience Comments" / "Banky Wellington" / "MENtality"
KEYWORDS_XLSX = ROOT / "Codebook and Keywords" / "NLC Proposed keywords.xlsx"
OUTPUT_DIR = ROOT / "Audience Demo Comments"
TEMP_DIR = ROOT / "temp" / "audience_demo_comments"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EMBEDDING_MODEL = "text-embedding-3-large"
LLM_MODEL = "gpt-4o-mini"

MIN_WORDS = 8
TARGET_PER_POST = 200
LLM_BATCH_SIZE = 20
LLM_CONCURRENCY = 16
EMBED_BATCH_SIZE = 256

CREATOR = "Banky Wellington"

SELECTED_POSTS = [
    {"post": "Masculinity + Money",                 "file": "Masculinity + Money.xlsx"},
    {"post": "Masculinity + Relationships",         "file": "Masculinity + Relationships.xlsx"},
    {"post": "Pt 2 Masculinity + Relationships",    "file": "Pt 2 Masculinity + Relationships.xlsx"},
    {"post": "Masculinity + Fatherhood",            "file": "Masculinity + Fatherhood.xlsx"},
    {"post": "Masculinity + Young Boys",            "file": "Masculinity + Young Boys.xlsx"},
    {"post": "Masculinity + Friendship",            "file": "Masculinity + Friendship.xlsx"},
]

# Anchors tuned for Banky's healthy-masculinity / MENtality framing — what it
# means to be a man, money, relationships, fatherhood, friendship, raising boys,
# vulnerability, accountability, plus regressive pushback patterns audiences use.
ANCHORS = [
    "what it means to be a real man and male identity",
    "men's responsibilities, accountability and emotional growth",
    "healthy masculinity, vulnerability and male mental health",
    "men opening up to other men about struggles and friendship",
    "fatherhood, raising sons, and modeling masculinity for young boys",
    "men and money — provider expectations, financial pressure on men",
    "marriage, relationships and what men should bring to the table",
    "gender roles and what women want vs what men should be",
    "personal testimony from a man about marriage, family or fatherhood",
    "advice to young men about love, responsibility and self-respect",
    "agreement with the creator's progressive / healthy-masculinity take",
    "disagreement, traditionalist or manosphere pushback against the creator",
    "criticism of toxic masculinity, ego, pride or chauvinism",
    "religious or cultural framing of male duty and family",
    "intergenerational change in how Nigerian men behave",
    "men supporting their wives, partners and women in their lives",
    "feminism, gender debate and male defensiveness",
]

SYSTEM_PROMPT = """You are a research coder reviewing audience comments on a Nigerian podcast (MENtality) hosted by Banky Wellington — a progressive male public figure focused on healthy masculinity. His themes: what it means to be a man; men and money; men and relationships; fatherhood and raising boys; male friendship and vulnerability; men holding themselves accountable; rejecting toxic masculinity while honoring tradition.

Mark a comment RELEVANT if it engages — in any way — with the post's themes. Be GENEROUS:
  • Direct discussion of masculinity, what makes a man, manhood, male identity.
  • Men's roles in marriage / relationships / family / fatherhood.
  • Provider pressure, financial responsibility, men and money.
  • Male vulnerability, mental health, emotional expression, asking for help.
  • Raising boys, modeling masculinity for the next generation.
  • Male friendship, brotherhood, peer accountability.
  • Agreement with Banky's healthy-masculinity / accountability take.
  • Disagreement, traditionalist or manosphere pushback (\"a real man should…\", \"this is feminism\", \"too soft\").
  • Personal testimony / lived experience about being a man, husband, father, son.
  • Advice to young men or to other men about responsibility, love, money, manhood.
  • Religion- or culture-framed takes on male duty (\"the bible says…\", \"in our culture…\").
  • Substantive reaction with a reason (\"this is true because…\", \"I disagree because…\").

Mark NOT RELEVANT only if:
  • Pure spam, ads, promotional links, follow-back requests.
  • Off-topic chatter (sports, the host's looks, music industry gossip).
  • Empty hype with zero content (\"nice one\", \"lmao\", \"first\", \"❤️\").
  • Pure faith praise with no masculinity content (\"Amen\", \"God bless this podcast\").
  • Pure insult of the host with no engagement on the topic.

Return a JSON object with key \"results\" whose value is a list of:
  {\"id\": <int>, \"relevant\": true|false, \"reason\": \"<short reason, 12 words max>\"}.
Output nothing else."""


# ---------------------------------------------------------------------------
# Loading & cleaning
# ---------------------------------------------------------------------------
def _normalize_text(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_post(meta):
    path = INPUT_DIR / meta["file"]
    df = pd.read_excel(path)
    text_col = "comment" if "comment" in df.columns else "text"
    df["raw_text"] = df[text_col].apply(_normalize_text)
    df["creator"] = CREATOR
    df["post"] = meta["post"]
    keep = ["creator", "post", "raw_text"]
    for aux in ("author", "likes", "reply_count"):
        if aux in df.columns:
            keep.append(aux)
    print(f"  · {meta['post'][:42]:<42}: {len(df):>4} rows")
    return df[keep]


# ---------------------------------------------------------------------------
# Substance gate
# ---------------------------------------------------------------------------
EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U00002600-\U000027BF\U0001F900-\U0001F9FF\U00002700-\U000027BF"
    "\U0001F100-\U0001F1FF]+",
    flags=re.UNICODE,
)
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", flags=re.IGNORECASE)
MENTION_PATTERN = re.compile(r"@\w+")


def strip_decorations(s):
    s = URL_PATTERN.sub(" ", s)
    s = MENTION_PATTERN.sub(" ", s)
    s = EMOJI_PATTERN.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def quality_signals(text):
    stripped = strip_decorations(text)
    words = re.findall(r"[A-Za-z']+", stripped)
    return pd.Series({
        "stripped_text": stripped,
        "n_words": len(words),
        "longest_word_len": max((len(w) for w in words), default=0),
    })


# ---------------------------------------------------------------------------
# OpenAI helpers
# ---------------------------------------------------------------------------
def embed_batch(client, texts, model=EMBEDDING_MODEL):
    resp = client.embeddings.create(model=model, input=list(texts))
    return np.array([d.embedding for d in resp.data])


def build_user_prompt(post_title, batch):
    lines = [f"Post: {post_title}", "", "Comments:"]
    for i, text in batch:
        lines.append(f"[{i}] {text.replace(chr(10), ' ')[:400]}")
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
                out = []
                for r in data.get("results", []):
                    lid = r.get("id")
                    if lid in local_to_global:
                        out.append((local_to_global[lid], bool(r.get("relevant")), r.get("reason", "")))
                return out
            except Exception as e:
                if attempt == 3:
                    print(f"    LLM batch failed: {e}")
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

    print(f"Dispatching {len(coroutines)} LLM batches × up to {LLM_BATCH_SIZE} comments")
    all_rows = []
    tasks = [asyncio.create_task(c) for c in coroutines]
    for fut in atqdm.as_completed(tasks, total=len(tasks), desc="LLM"):
        rows = await fut
        all_rows.extend(rows)
    return all_rows


# ---------------------------------------------------------------------------
# Faith strip (matches the regex used on the existing demo files)
# ---------------------------------------------------------------------------
FAITH_PATTERN = re.compile(
    r"\b(bible|biblical|scripture|verses?|"
    r"jesus|christ|christianity|christian|"
    r"prophet|prophecy|prophesy|prophesied|isaiah|psalm|proverbs|matthew|mathew|john|"
    r"pastor|church|mosque|"
    r"amen|hallelujah|anointed|"
    r"islam|islamic|muslim|allah|qur'?an|sharia|"
    r"worship|sermon|"
    r"shiloh|jerry\s+eze|kayamata|"
    r"godly|godliness|"
    r"sinner|sinful|repent|holy\s+spirit|holy\s+book|holy\s+ghost|"
    r"hellfire|heavenly|"
    r"divine\s+\w+|born\s+again)\b",
    flags=re.IGNORECASE,
)
GOD_PHRASES = re.compile(
    r"\b(god['’]s\s+(grace|will|word|name|plan|hand|mercy|love|wisdom|judgment)|"
    r"(thank|fear|praise|by|with|to|for)\s+god\b|"
    r"god\s+(bless|will|said|created|inspired|punish|judge|forbid|knows|grace)|"
    r"may\s+(god|allah)|"
    r"in\s+jesus|"
    r"the\s+lord|"
    r"holy\s+(book|spirit|ghost|bible))",
    flags=re.IGNORECASE,
)


def is_faith(t):
    return bool(FAITH_PATTERN.search(t)) or bool(GOD_PHRASES.search(t))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def _safe(name):
    return re.sub(r"[^\w\- ]+", "", name).strip()


async def main_async():
    print("=== 1. Load ===")
    raw_frames = [load_post(p) for p in SELECTED_POSTS]
    raw = pd.concat(raw_frames, ignore_index=True)
    print(f"\nTotal raw rows: {len(raw):,}")

    print("\n=== 2. Substance gate ===")
    signals = raw["raw_text"].apply(quality_signals)
    df = pd.concat([raw, signals], axis=1)
    df["is_substantive"] = (df["n_words"] >= MIN_WORDS) & (df["longest_word_len"] >= 3)
    print(f"Substantive: {int(df['is_substantive'].sum()):,} / {len(df):,} "
          f"({df['is_substantive'].mean():.1%})")

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
    print(f"With keyword: {int((df['is_substantive'] & df['has_keyword']).sum())} / "
          f"{int(df['is_substantive'].sum())}")

    print("\n=== 4. Embeddings ===")
    sub = df[df["is_substantive"]].copy().reset_index(drop=True)
    client = OpenAI()
    anchor_emb = embed_batch(client, ANCHORS)
    anchor_emb = anchor_emb / np.linalg.norm(anchor_emb, axis=1, keepdims=True)

    embeds_path = TEMP_DIR / "banky_comment_embeddings.npy"
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

    print("\n=== 5. LLM relevance ===")
    llm_results_path = TEMP_DIR / "banky_llm_results.parquet"
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
    print(f"Selected pre-faith-strip: {len(selected)}")

    print("\n=== 7. Faith strip ===")
    faith_mask = selected["raw_text"].astype(str).apply(is_faith)
    print(f"Removing {int(faith_mask.sum())} faith-related rows")
    selected = selected.loc[~faith_mask].reset_index(drop=True)
    print(f"After faith strip: {len(selected)}")

    print("\n=== 8. Export ===")
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

    summary_path = OUTPUT_DIR / "_summary.xlsx"
    if summary_path.exists():
        existing = pd.read_excel(summary_path)
        existing = existing[existing["creator"] != CREATOR]
        merged = pd.concat([existing, pd.DataFrame(summary_rows)], ignore_index=True)
    else:
        merged = pd.DataFrame(summary_rows)
    merged.to_excel(summary_path, index=False)
    print(f"\nBanky total: {sum(r['rows'] for r in summary_rows)}")
    print(f"Updated {summary_path.relative_to(ROOT)}")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
