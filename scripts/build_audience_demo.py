"""Build the final scope-relevant audience demo dataset for any Nigeria creator.

ONE generalised pipeline (replaces three separate creator-specific scripts).
Per-creator differences live in `CREATOR_CONFIGS` — anchors, system prompt,
sources, OP handle. The shared pipeline:

  1. Load + normalise raw comments (drop OP self-replies + paraphrase quotes)
  2. Substance gate (>7 words after stripping URLs / mentions / emojis)
  3. Keyword annotation against NLC Nigeria lexicon
  4. Embedding similarity to per-creator anchor phrases (text-embedding-3-large)
  5. Lenient LLM relevance check (gpt-4o-mini) tuned per orientation
  6. Composite score: 0.20*kw + 0.35*sim + 0.45*llm
  7. Top-N LLM-relevant per post (TARGET_PER_POST cap; or all if fewer)
  8. Faith strip (substantive religious content removed; colloquial idioms kept)
  9. Output:
       Nigeria/Audience Comments - Final/<creator>_<slug>.xlsx  (single `text` col)
       _summary.xlsx updated

Usage:
  python scripts/build_audience_demo.py --creator agba_shola
  python scripts/build_audience_demo.py --creator deyemi
  python scripts/build_audience_demo.py --creator banky
  python scripts/build_audience_demo.py --creator all
"""
from __future__ import annotations

import argparse
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

RAW_ROOT = ROOT / "Nigeria/Audience Comments - Raw"
KEYWORDS_XLSX = ROOT / "Codebook and Keywords" / "NLC Proposed keywords.xlsx"
OUTPUT_DIR = ROOT / "Nigeria/Audience Comments - Final"
TEMP_DIR = ROOT / "temp" / "audience_demo"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EMBEDDING_MODEL = "text-embedding-3-large"
LLM_MODEL = "gpt-4o-mini"
MIN_WORDS = 8
TARGET_PER_POST = 200
LLM_BATCH_SIZE = 20
LLM_CONCURRENCY = 16
EMBED_BATCH_SIZE = 256


# ---------------------------------------------------------------------------
# Per-creator configurations — the only thing that differs across pipelines
# ---------------------------------------------------------------------------

REGRESSIVE_ANCHORS = [
    "views on what it means to be a man",
    "traditional gender roles and male provider expectations",
    "female submission, obedience and the role of a wife",
    "men as the prize and women competing for husbands",
    "marriage, infidelity and whether to leave a cheating husband",
    "polygamy and female scarcity narratives",
    "divorce, second-hand wives and the marriage market",
    "advice to married women about staying or leaving",
    "biblical or religious framing of marriage and gender",
    "agreement with the creator's regressive take on women or marriage",
    "disagreement or feminist pushback against the creator",
    "personal testimony from a man or woman about marriage and relationships",
    "feminism, misogyny and women's rights",
    "men's responsibilities, accountability and male behaviour",
    "sex, dating standards and sexual double standards",
]

REGRESSIVE_PROMPT = """You are a research coder reviewing audience comments on Nigerian social-media posts by REGRESSIVE male-influencers (themes: women should not leave cheating husbands; men are the prize; female scarcity; submission; biblical framing of marriage).

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
Output nothing else."""


DEYEMI_ANCHORS = [
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

DEYEMI_PROMPT = """You are a research coder reviewing audience comments on Nigerian social-media posts by a PROGRESSIVE male public figure (Deyemi Okanlawon). His themes: stop raping women; men must hold men accountable for sexual violence; anti-rape advocacy; pushback against male defensiveness, false-accusation deflection, and whataboutism; gender debate; male responsibility.

Mark a comment RELEVANT if it engages — in any way — with the post's themes. Be GENEROUS:
  • Direct discussion of rape, sexual violence, gender-based violence, false accusations, due process, men's accountability, women's safety.
  • Boy-child / male-victim framing, "what about boys/men?" deflection, calls for protecting men from false accusations.
  • Discussion of masculinity, what real men should do, gender roles in marriage / family.
  • Feminist support OR anti-feminist pushback against the creator's position.
  • Personal testimony / lived experience about sexual violence, harassment, abuse, false accusations.
  • Religion- or culture-framed takes on justice, mercy, accountability ("the bible said…", "in our culture…").
  • Substantive reaction with a reason ("this is true because…", "I disagree because…").
  • Simi-related backlash about predator/child-safety claims.

Mark NOT RELEVANT only if:
  • Pure spam, ads, promotional links, follow-back requests.
  • Off-topic chatter (sports, an unrelated political case, the creator's looks).
  • Empty hype with zero content ("nice one", "lmao", "first", "preach").
  • Pure insult of the creator with no engagement on the topic.

Return a JSON object with key "results" whose value is a list of:
  {"id": <int>, "relevant": true|false, "reason": "<short reason, 12 words max>"}.
Output nothing else."""


BANKY_ANCHORS = [
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

BANKY_PROMPT = """You are a research coder reviewing audience comments on a Nigerian podcast (MENtality) hosted by Banky Wellington — a progressive male public figure focused on healthy masculinity. His themes: what it means to be a man; men and money; men and relationships; fatherhood and raising boys; male friendship and vulnerability; men holding themselves accountable; rejecting toxic masculinity while honoring tradition.

Mark a comment RELEVANT if it engages — in any way — with the post's themes. Be GENEROUS:
  • Direct discussion of masculinity, what makes a man, manhood, male identity.
  • Men's roles in marriage / relationships / family / fatherhood.
  • Provider pressure, financial responsibility, men and money.
  • Male vulnerability, mental health, emotional expression, asking for help.
  • Raising boys, modeling masculinity for the next generation.
  • Male friendship, brotherhood, peer accountability.
  • Agreement with Banky's healthy-masculinity / accountability take.
  • Disagreement, traditionalist or manosphere pushback ("a real man should…", "this is feminism", "too soft").
  • Personal testimony / lived experience about being a man, husband, father, son.
  • Advice to young men or to other men about responsibility, love, money, manhood.
  • Religion- or culture-framed takes on male duty ("the bible says…", "in our culture…").
  • Substantive reaction with a reason ("this is true because…", "I disagree because…").

Mark NOT RELEVANT only if:
  • Pure spam, ads, promotional links, follow-back requests.
  • Off-topic chatter (sports, the host's looks, music industry gossip).
  • Empty hype with zero content ("nice one", "lmao", "first", "❤️").
  • Pure faith praise with no masculinity content ("Amen", "God bless this podcast").
  • Pure insult of the host with no engagement on the topic.

Return a JSON object with key "results" whose value is a list of:
  {"id": <int>, "relevant": true|false, "reason": "<short reason, 12 words max>"}.
Output nothing else."""


CREATOR_CONFIGS = {
    "agba_shola": {
        "label": "Regressive Nigeria pair (Agba John Doe + Shola)",
        "anchors": REGRESSIVE_ANCHORS,
        "system_prompt": REGRESSIVE_PROMPT,
        "posts": [
            {
                "creator": "Agba John Doe", "creator_handle": "jon_d_doe",
                "post": "Never Leave Marriage Because Husband Cheated",
                "rel_path": "Agba John Doe/Never Leave Marriage Because Husband Cheated.xlsx",
                "out_name": "agba_tweet.xlsx",
            },
            {
                "creator": "Shola", "creator_handle": "itsSh0la",
                "post": "7 Women Will Beg One Man to Marry",
                "rel_path": "Shola/7 Women Will Beg One Man to Marry.xlsx",
                "out_name": "shola_tweet.xlsx",
            },
        ],
    },
    "deyemi": {
        "label": "Deyemi Okanlawon (progressive — Stop Raping Women response)",
        "anchors": DEYEMI_ANCHORS,
        "system_prompt": DEYEMI_PROMPT,
        "posts": [
            {
                "creator": "Deyemi Okanlawon", "creator_handle": "_deyemi",
                "post": "Stop Raping Women Response",
                "rel_path": "Deyemi Okanlawon/Stop Raping Women Response.xlsx",
                "out_name": "deyemi_tweet.xlsx",
            },
        ],
    },
    "banky": {
        "label": "Banky Wellington MENtality (progressive — 6 episodes pooled)",
        "anchors": BANKY_ANCHORS,
        "system_prompt": BANKY_PROMPT,
        "posts": [
            {
                "creator": "Banky Wellington", "creator_handle": None,
                "post": ep, "rel_path": f"Banky Wellington/MENtality/{ep}.xlsx",
                "out_name": "banky_podcast.xlsx",  # all 6 pooled into one file
            }
            for ep in [
                "Masculinity + Money",
                "Masculinity + Relationships",
                "Pt 2 Masculinity + Relationships",
                "Masculinity + Fatherhood",
                "Masculinity + Young Boys",
                "Masculinity + Friendship",
            ]
        ],
    },
}


# ---------------------------------------------------------------------------
# Shared pipeline
# ---------------------------------------------------------------------------
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U00002600-\U000027BF\U0001F900-\U0001F9FF\U00002700-\U000027BF"
    "\U0001F100-\U0001F1FF]+",
    flags=re.UNICODE,
)
URL = re.compile(r"https?://\S+|www\.\S+", flags=re.IGNORECASE)
MENTION = re.compile(r"@\w+")


def normalize_text(s):
    if not isinstance(s, str): return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def strip_decorations(s):
    s = URL.sub(" ", s)
    s = MENTION.sub(" ", s)
    s = EMOJI.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def quality_signals(text):
    stripped = strip_decorations(text)
    words = re.findall(r"[A-Za-z']+", stripped)
    return pd.Series({
        "stripped_text": stripped,
        "n_words": len(words),
        "longest_word_len": max((len(w) for w in words), default=0),
    })


def load_post(meta):
    path = RAW_ROOT / meta["rel_path"]
    df = pd.read_excel(path)
    text_col = "comment" if "comment" in df.columns else "text"
    handle = meta.get("creator_handle")

    if handle and "author" in df.columns:
        df = df.loc[df["author"].astype(str).str.lower() != handle.lower()].reset_index(drop=True)

    df["raw_text"] = df[text_col].apply(normalize_text)
    df["creator"] = meta["creator"]
    df["post"] = meta["post"]
    keep = ["creator", "post", "raw_text"]
    for aux in ("author", "likes", "reply_count", "replies", "retweets", "timestamp", "url"):
        if aux in df.columns:
            keep.append(aux)
    print(f"  · {meta['post'][:42]:<42}: {len(df):>4} rows")
    return df[keep]


def embed_batch(client, texts):
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=list(texts))
    return np.array([d.embedding for d in resp.data])


def build_user_prompt(post_title, batch):
    lines = [f"Post: {post_title}", "", "Comments:"]
    for i, text in batch:
        lines.append(f"[{i}] {text.replace(chr(10), ' ')[:400]}")
    return "\n".join(lines)


async def classify_batch(async_client, system_prompt, local_to_global, batch, post_title, sem):
    async with sem:
        for attempt in range(4):
            try:
                resp = await async_client.chat.completions.create(
                    model=LLM_MODEL,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
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
                    return [(local_to_global[i], None, f"error: {e}") for i, _ in batch]
                await asyncio.sleep(2 ** attempt)


async def classify_all(async_client, system_prompt, sub_df):
    sem = asyncio.Semaphore(LLM_CONCURRENCY)
    coroutines = []
    for (creator, post), g in sub_df.groupby(["creator", "post"]):
        g_idx = g.index.tolist()
        texts = g["stripped_text"].tolist()
        for start in range(0, len(texts), LLM_BATCH_SIZE):
            chunk_local = list(enumerate(texts[start:start + LLM_BATCH_SIZE], start=start))
            local_to_global = {local_i: g_idx[local_i] for local_i, _ in chunk_local}
            coroutines.append(classify_batch(async_client, system_prompt, local_to_global, chunk_local, post, sem))

    print(f"Dispatching {len(coroutines)} LLM batches × up to {LLM_BATCH_SIZE} comments")
    rows = []
    tasks = [asyncio.create_task(c) for c in coroutines]
    for fut in atqdm.as_completed(tasks, total=len(tasks), desc="LLM"):
        rows.extend(await fut)
    return rows


# Faith strip — same regex used across all 4 final files
FAITH_LOOSE = re.compile(
    r"\b(god|gods|jesus|christ|christian|christianity|bible|biblical|"
    r"pastor|preacher|reverend|congregation|church|mosque|temple|"
    r"amen|hallelujah|prayer|praying|prayed|prayers|"
    r"blessing|blessed|spiritual|faith|believer|believers|salvation|"
    r"sin|sinner|deity|holy|sacred|"
    r"scriptural|scripture|verse|verses|prophet|prophecy|"
    r"islam|islamic|muslim|allah|quran|sharia|gospel|"
    r"divine|heaven|heavens|hell|repent|"
    r"isaiah|psalm|proverbs|matthew|john|luke|mark)\b",
    flags=re.IGNORECASE,
)


def is_faith(text):
    return bool(FAITH_LOOSE.search(str(text)))


def safe_slug(name):
    return re.sub(r"[^\w\- ]+", "", name).strip()


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------
async def run_pipeline(config_key):
    cfg = CREATOR_CONFIGS[config_key]
    print(f"\n========== {cfg['label']} ==========")

    # 1. Load
    print("\n=== 1. Load ===")
    raw_frames = [load_post(p) for p in cfg["posts"]]
    raw = pd.concat(raw_frames, ignore_index=True)
    print(f"\nTotal raw rows: {len(raw):,}")

    # 2. Substance
    print("\n=== 2. Substance gate ===")
    sig = raw["raw_text"].apply(quality_signals)
    df = pd.concat([raw, sig], axis=1)
    df["is_substantive"] = (df["n_words"] >= MIN_WORDS) & (df["longest_word_len"] >= 3)
    print(f"Substantive: {int(df['is_substantive'].sum()):,} / {len(df):,}")

    # 3. Keywords
    print("\n=== 3. Keyword annotation ===")
    kw_df = pd.read_excel(KEYWORDS_XLSX, sheet_name="Nigeria")
    kw_df = kw_df.dropna(subset=["Keyword"])
    kw_df["Keyword"] = kw_df["Keyword"].astype(str).str.strip()
    kw_df = kw_df[kw_df["Keyword"].str.len() >= 2]
    rel_col = "Relevance to manosphere conversations"
    kw_set = set(kw_df.loc[kw_df[rel_col].str.contains("Highly|Moderately", na=False), "Keyword"].str.lower())
    escaped = sorted([re.escape(k) for k in kw_set], key=len, reverse=True)
    kw_regex = re.compile(r"\b(" + "|".join(escaped) + r")\b", flags=re.IGNORECASE) if escaped else None

    def kw_hits(t):
        return list(dict.fromkeys(kw_regex.findall(t.lower()))) if kw_regex and t else []

    df["keyword_hits"] = df["raw_text"].apply(kw_hits)
    df["has_keyword"] = df["keyword_hits"].str.len() > 0

    # 4. Embeddings
    print("\n=== 4. Embeddings ===")
    sub = df[df["is_substantive"]].copy().reset_index(drop=True)
    client = OpenAI()
    anchor_emb = embed_batch(client, cfg["anchors"])
    anchor_emb /= np.linalg.norm(anchor_emb, axis=1, keepdims=True)

    embeds_path = TEMP_DIR / f"{config_key}_embeddings.npy"
    if embeds_path.exists() and len(np.load(embeds_path)) == len(sub):
        emb = np.load(embeds_path)
        print(f"Loaded cached embeddings: {emb.shape}")
    else:
        chunks = []
        for start in tqdm(range(0, len(sub), EMBED_BATCH_SIZE), desc="embedding"):
            chunks.append(embed_batch(client, sub["stripped_text"].iloc[start:start + EMBED_BATCH_SIZE].tolist()))
        emb = np.vstack(chunks)
        np.save(embeds_path, emb)

    emb_norm = emb / np.linalg.norm(emb, axis=1, keepdims=True)
    sim = emb_norm @ anchor_emb.T
    sub["sim_max"] = sim.max(axis=1)

    # 5. LLM
    print("\n=== 5. LLM relevance ===")
    llm_path = TEMP_DIR / f"{config_key}_llm.parquet"
    if llm_path.exists():
        llm_df = pd.read_parquet(llm_path)
        print(f"Loaded cached LLM results: {len(llm_df):,}")
    else:
        async_client = AsyncOpenAI()
        rows = await classify_all(async_client, cfg["system_prompt"], sub)
        llm_df = pd.DataFrame(
            [{"sub_idx": idx, "llm_relevant": rel, "llm_reason": reason}
             for idx, rel, reason in rows]
        ).drop_duplicates("sub_idx")
        llm_df.to_parquet(llm_path)
    sub = sub.merge(llm_df, left_index=True, right_on="sub_idx", how="left").drop(columns="sub_idx").reset_index(drop=True)
    sub["llm_relevant"] = sub["llm_relevant"].fillna(False).astype(bool)
    print(f"LLM-relevant rate: {sub['llm_relevant'].mean():.1%}")

    # 6. Composite + top-N + faith strip
    print("\n=== 6. Composite + top-N + faith strip ===")
    sub["sim_scaled"] = sub.groupby("post")["sim_max"].transform(
        lambda s: (s - s.min()) / (s.max() - s.min() + 1e-9)
    )
    sub["score"] = (
        0.20 * sub["has_keyword"].astype(float)
        + 0.35 * sub["sim_scaled"]
        + 0.45 * sub["llm_relevant"].astype(float)
    )

    selected = []
    for (creator, post), g in sub.groupby(["creator", "post"]):
        eligible = g[g["llm_relevant"]].sort_values("score", ascending=False)
        top = eligible.head(TARGET_PER_POST).copy()
        top["rank"] = range(1, len(top) + 1)
        selected.append(top)
    selected = pd.concat(selected, ignore_index=True)

    faith_mask = selected["raw_text"].apply(is_faith)
    print(f"Pre-faith: {len(selected)} | faith-stripped: {int(faith_mask.sum())} | final: {len(selected) - int(faith_mask.sum())}")
    selected = selected.loc[~faith_mask].reset_index(drop=True)

    # 7. Export — group by output file (banky pools all 6 episodes into one)
    print("\n=== 7. Export ===")
    by_out = {}
    for _, row in selected.iterrows():
        out_name = next(p["out_name"] for p in cfg["posts"] if p["post"] == row["post"])
        by_out.setdefault(out_name, []).append(row["raw_text"])

    for out_name, texts in by_out.items():
        out_path = OUTPUT_DIR / out_name
        pd.DataFrame({"text": texts}).to_excel(out_path, index=False)
        print(f"  wrote {out_path.relative_to(ROOT)}: {len(texts)} rows")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--creator", choices=list(CREATOR_CONFIGS.keys()) + ["all"], required=True)
    args = parser.parse_args()

    targets = list(CREATOR_CONFIGS.keys()) if args.creator == "all" else [args.creator]
    for key in targets:
        asyncio.run(run_pipeline(key))


if __name__ == "__main__":
    main()
