"""Filter the 1,174 Falz tweets down to a clean progressive masculinity content set.

Pipeline:
  1. Drop retweets (keep only Falz's own writing).
  2. Drop ultra-short / pure URL / link-only.
  3. Broad keyword pre-filter for any masculinity / gender / accountability content.
  4. gpt-4o 2-stage filter:
       Stage A: Is this on-scope masculinity content?
       Stage B: Does it match a regressive pattern that would contaminate a progressive dataset?
       Accept iff (A=yes) AND (B=no).
  5. Orientation audit on accepts (drop anything still flagged regressive).
  6. Generate gpt-4o context note per accepted tweet.
  7. Write to Nigeria/Content Analysis/Content - Final/Falz_Twitter.xlsx
     with schema matching other creator files.
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm as atqdm


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY missing"

SRC      = ROOT / "Nigeria" / "Scraped Tweets" / "Falz_all_tweets.xlsx"
OUT_PATH = ROOT / "Nigeria" / "Content Analysis" / "Content - Final" / "Falz_Twitter.xlsx"
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

LLM_MODEL   = "gpt-4o"
CONCURRENCY = 6


def deep_decode(s):
    s = str(s)
    for _ in range(4):
        n = html.unescape(s)
        if n == s:
            break
        s = n
    return s


SCOPE_PROMPT = """You are filtering tweets from Falz (Folarin Falana) — a Nigerian rapper / lawyer / activist — for a PROGRESSIVE MASCULINITY content analysis (Norman Lear Center / Gates Foundation).

Scope is PROGRESSIVE MASCULINITY — Falz as a male voice taking a stance on gender, accountability, women's protection, or men's behaviour.

STAGE A — Does this tweet engage progressive masculinity / male-ally content?
ACCEPT if any of these is clearly present:
  - male accountability for misogyny, abuse, sexual violence
  - rape culture, consent, sexual violence (especially female victims)
  - calling out men's bad behaviour
  - false-accusation / due-process discourse on gendered cases
  - male emotional life, vulnerability, mental health, therapy
  - fatherhood, raising boys, parenting
  - marriage, partnership, dating, divorce, sexual ethics
  - provider pressure, men + money expectations
  - gender debate, feminism, "men vs women", equality
  - masculinity + faith / Christianity-and-manhood
  - male critique of patriarchy / toxic masculinity
  - male endorsement of women's agency, women's leadership, women's safety
  - protection of women / children when male perpetrators implied
  - sexual harassment / assault discourse
  - violence against women SPECIFICALLY (e.g. femicide, rape victims like Uwa, Tina, Bolanle Raheem) — Falz amplifying these IS progressive male voice
  - police brutality / state violence WHERE the victim is a woman, OR male perpetrators are highlighted, OR Falz frames it as a justice/accountability issue (his EndSARS leadership IS part of his progressive male public identity)
  - women's empowerment / opportunities (scholarships, IWD) when accompanied by commentary or framing
  - generic "we must protect lives" / "justice must be served" content tied to specific named victims (often women or vulnerable men)

OFF-SCOPE (REJECT):
  - PURE music / album / single / tour / artist promo
  - PURE movie / TV / business / event promo
  - generic Nigerian economy / fuel / japa / election with NO violence / women / accountability angle
  - food, sports, weather, birthday, condolence-only, RIP-only
  - vague replies ("lol", "yes bro") needing missing parent tweet
  - religious-only with no gender / community frame
  - shoutouts to artists / friends with no substance
  - generic political opinion with NO connection to violence, women, or men's behaviour

STAGE B — Does the tweet match a REGRESSIVE pattern that would contaminate a progressive dataset?
  - "men are tired", "world kills men", male-victimhood without acknowledging female suffering
  - alimony / divorce-court grievances
  - "men are scum" sarcastic deflection / whataboutism
  - mocking male DV victims or male tears
  - provider-supremacy framings (even tongue-in-cheek)
  - "if she does it too" / double-standards-cut-both-ways gotchas
  - feminist-mocking, "modern women" complaints
  - manosphere hierarchies (alpha/beta, high-value man, man-child)
  - hypergamy resentment, women-as-transactional

ACCEPT only if (A=yes) AND (B=no).

ALSO REJECT (out of scope regardless of stage):
  - PURE music / album / single promo with no other content
  - PURE movie / Nollywood / TV show / business / event promo
  - generic Nigerian economy / fuel / japa / electricity gripes with NO gender / justice / violence angle
  - food, sports, weather, birthday, condolence, RIP
  - vague replies whose meaning depends on missing parent tweet (e.g. "lol", "yes bro")
  - religious-only with no gender / justice / community frame
  - pure shoutouts / congratulations to other artists with no substance

Be reasonable but strict. The tweet should make a clear, codable claim or observation about a gender / masculinity / women-protection theme.

TWEET:
\"\"\"{text}\"\"\"

JSON only:
{{"stage_a_on_scope": true | false,
  "stage_b_regressive_pattern": true | false,
  "accept": true | false,
  "theme": "<short label e.g. 'rape culture', 'male accountability', 'fatherhood', 'gender debate', 'consent', 'EndSARS / state violence'; blank if rejected>",
  "reason": "<one short sentence>"}}"""


CTX_PROMPT = """One concise sentence (max 25 words) describing what this Falz (Folarin Falana) tweet is about, for a research coder unfamiliar with Nigerian context. Note any Pidgin / Yoruba / Nigerian references the coder might miss.

TWEET:
\"\"\"{text}\"\"\"

JSON only: {{"context": "..."}}"""


AUDIT_PROMPT = """Classify this snippet's gender stance:

PROGRESSIVE = challenges patriarchy, male accountability, vulnerability, gender equality, victim protection.
REGRESSIVE = reinforces patriarchy/manosphere; men-as-victims, hypergamy resentment, mocking male tears/DV, polygamy advocacy.
NEUTRAL = observation without taking sides.

SNIPPET: \"\"\"{text}\"\"\"
JSON: {{"orientation":"progressive|regressive|neutral","confidence":"high|medium|low","reason":"<sentence>"}}"""


KW = re.compile(
    r"\b("
    r"man|men|woman|women|wife|wives|husband|husbands|girl|boy|girls|boys|"
    r"father|fatherhood|dad|daddy|mom|mama|mother|son|sons|daughter|daughters|"
    r"marriage|marry|married|divorce|relationship|partner|spouse|wedding|"
    r"rape|rapist|consent|victim|survivor|abuse|abuser|abused|assault|harass|"
    r"accountab|toxic|patriarchy|feminism|feminist|misogyn|"
    r"masculin|manhood|womanhood|gender|sexism|sexist|"
    r"therapy|trauma|depres|suicid|cry|tears|vulnerab|emotion|mental|"
    r"provider|breadwinner|"
    r"defamat|stigma|shame|"
    r"sex|sexual|infidelity|cheat|virgin|"
    r"male|female|"
    r"sars|endsars|brutal|violen|justice|police|"
    r"protect|leader|"
    r"speak|silent|silenc|listen|hear|believe|"
    r"brother|sister|"
    r"church|pastor|god|jesus|bible|faith|"
    r"abeg|wahala|na\s+"
    r")\b",
    re.IGNORECASE,
)


async def call_llm(client, sem, prompt):
    async with sem:
        for attempt in range(5):
            try:
                resp = await client.chat.completions.create(
                    model=LLM_MODEL, temperature=0,
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": prompt}],
                )
                return json.loads(resp.choices[0].message.content)
            except Exception as e:
                err = str(e)
                if "429" in err or "rate" in err.lower():
                    await asyncio.sleep(5 * (2 ** attempt))
                    continue
                if attempt == 4:
                    return {}
                await asyncio.sleep(2 ** attempt)


async def main():
    print("=== Falz progressive filter pipeline ===", flush=True)
    df = pd.read_excel(SRC)
    print(f"  scraped tweets:           {len(df)}", flush=True)

    # Drop retweets, keep own content
    df = df[~df["is_retweet"].astype(bool)].copy()
    print(f"  after dropping retweets:  {len(df)}", flush=True)

    # Decode HTML entities
    df["text"] = df["text"].astype(str).map(deep_decode).str.strip()
    df = df[df["text"] != ""].drop_duplicates(subset="text").reset_index(drop=True)

    # Drop URL-only and ultra-short
    df["n_words"] = df["text"].str.split().apply(len)
    df = df[df["n_words"] >= 6].reset_index(drop=True)
    df = df[~df["text"].str.match(r"^https?://\S+\s*$")].reset_index(drop=True)
    print(f"  after substance filter:   {len(df)}", flush=True)

    # Keyword pre-filter (broad — let LLM do the real filtering)
    df["has_kw"] = df["text"].str.contains(KW, regex=True, na=False)
    candidates = df[df["has_kw"]].reset_index(drop=True)
    print(f"  keyword-matching:         {len(candidates)}", flush=True)
    # Also evaluate non-keyword tweets in case our regex missed scope content
    non_kw = df[~df["has_kw"]].reset_index(drop=True)
    # Take tweets >=10 words from non-kw to test (broader net)
    non_kw_substantive = non_kw[non_kw["n_words"] >= 10].reset_index(drop=True)
    candidates = pd.concat([candidates, non_kw_substantive], ignore_index=True).drop_duplicates(subset="text").reset_index(drop=True)
    print(f"  candidates (incl. non-keyword substantive): {len(candidates)}", flush=True)

    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    print(f"\n  pass 1: scope + regressive-reject ({len(candidates)} gpt-4o calls)…", flush=True)
    coros = [call_llm(client, sem, SCOPE_PROMPT.format(text=str(t)[:1500])) for t in candidates["text"]]
    results = await atqdm.gather(*coros, desc="scope")

    accepted = []
    rej_offscope = rej_regressive = 0
    for i, r in enumerate(results):
        if r.get("accept") is True:
            accepted.append({
                "text":  str(candidates.iloc[i]["text"]),
                "url":   candidates.iloc[i].get("tweet_link"),
                "theme": r.get("theme", ""),
                "reason": r.get("reason", ""),
            })
        elif r.get("stage_b_regressive_pattern") is True:
            rej_regressive += 1
        else:
            rej_offscope += 1
    print(f"  accepted:           {len(accepted)}", flush=True)
    print(f"  rejected regressive: {rej_regressive}", flush=True)
    print(f"  rejected off-scope:  {rej_offscope}", flush=True)

    if not accepted:
        return

    # Pass 2: orientation audit on accepts (catch sneaky regressive)
    print(f"\n  pass 2: orientation audit on {len(accepted)} accepts…", flush=True)
    audit_coros = [call_llm(client, sem, AUDIT_PROMPT.format(text=a["text"][:1500])) for a in accepted]
    audit_results = await atqdm.gather(*audit_coros, desc="audit")
    clean = []
    dropped_regressive = 0
    for a, ar in zip(accepted, audit_results):
        if ar.get("orientation") == "regressive" and ar.get("confidence") in ("high", "medium"):
            dropped_regressive += 1
            continue
        clean.append(a)
    print(f"  audit dropped regressive contamination: {dropped_regressive}", flush=True)
    print(f"  clean accepts after audit: {len(clean)}", flush=True)

    if not clean:
        return

    # Pass 3: generate context notes
    print(f"\n  pass 3: context notes ({len(clean)} gpt-4o calls)…", flush=True)
    ctx_coros = [call_llm(client, sem, CTX_PROMPT.format(text=a["text"][:1500])) for a in clean]
    ctx_results = await atqdm.gather(*ctx_coros, desc="ctx")

    rows = [{
        "Segment ID":   f"FAZ_{i+1:03d}",
        "Influencer":   "Falz",
        "Platform":     "X",
        "Content Type": "Tweet",
        "Context (NOT CODED - comprehension only)": c.get("context", a.get("reason", "")),
        "Verbatim Text (CODE THIS)": a["text"],
    } for i, (a, c) in enumerate(zip(clean, ctx_results))]
    out = pd.DataFrame(rows)
    out.to_excel(OUT_PATH, index=False)
    print(f"\n  → {OUT_PATH.relative_to(ROOT)}: {len(out)} clean Falz tweets", flush=True)

    # Theme breakdown
    from collections import Counter
    themes = Counter(a["theme"] for a in clean)
    print(f"\n  theme breakdown:", flush=True)
    for theme, count in themes.most_common(15):
        print(f"    {count:>3}  {theme}", flush=True)

    # Project total
    final_dir = OUT_PATH.parent
    grand = sum(len(pd.read_excel(p)) for p in sorted(final_dir.glob("*.xlsx")) if not p.name.startswith("~$"))
    print(f"\n=== PROJECT TOTAL: {grand} ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
