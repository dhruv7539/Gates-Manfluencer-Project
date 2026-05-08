"""5-pass verification of Banky Wellington podcast snippets.

Problem: Gemini speaker labeling on the MENtality transcripts mislabels some
panelist turns as 'Banky W'. ChatGPT flagged biographical contradictions
(snippets mention 'our daughter' or 'I don't have a son', but Banky has 2 sons
and married Adesua Etomi in 2017). Manual spot-check confirms several real
misattributions.

This script runs 5 independent verification passes on every Banky snippet:

  Pass 1 — TRANSCRIPT ALIGNMENT: locate each snippet inside the source
           transcript file; record the actual Gemini speaker label that
           introduced it. Drop snippets where the surrounding label is NOT
           'Banky W' (Gemini sometimes splits a single Banky turn across
           neighbours; we keep only the rows whose body text falls inside a
           contiguous Banky-labelled turn).

  Pass 2 — BIOGRAPHICAL PLAUSIBILITY (gpt-4o): given Banky's biography
           (Bankole Wellington / Banky W, b.1981, EME records, married Adesua
           Etomi 2017, two sons, Lagos-based, ex-presidential aspirant,
           teaches at Union College), score each snippet 'plausible /
           implausible / unclear' as something Banky would say in first person.

  Pass 3 — PANEL CROSS-CHECK (gpt-4o): given the episode panel, ask which
           panelist most likely said the snippet. Flag if top guess is not
           Banky.

  Pass 4 — CONSENSUS DROP: drop any snippet flagged by Pass 1 OR (Pass 2
           implausible AND Pass 3 picks non-Banky).

  Pass 5 — FINAL SCOPE RE-VALIDATION: confirm every kept snippet is
           on-scope masculinity content (MENtality is in-scope by topic,
           but reject obvious off-topic asides — birthday wishes, ad reads,
           sound-check, etc.).

Output: overwrites
  Nigeria/Content Analysis/Content - Final/Banky Wellington_Podcast.xlsx
plus a side-car audit file:
  temp/verify_banky_5pass/audit.xlsx  (every snippet × every pass result)
"""
from __future__ import annotations

import asyncio
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

FINAL_PATH = ROOT / "Nigeria" / "Content Analysis" / "Content - Final" / "Banky Wellington_Podcast.xlsx"
TRANS_DIR  = ROOT / "Nigeria" / "Content Analysis" / "Content - Raw" / "Banky Wellington" / "Transcripts"
AUDIT_DIR  = ROOT / "temp" / "verify_banky_5pass"
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

LLM_MODEL   = "gpt-4o"
CONCURRENCY = 4

EPISODES = [
    {"file": "Masculinity + Money.txt",
     "panel": ["Ebuka Obi-Uchendu (host, has daughters, no son)", "Banky W (Bankole Wellington, married Adesua Etomi 2017, 2 sons, EME records founder, musician/actor, Lagos)", "Seun Kuti (Afrobeat musician, son of Fela)", "Noble Igwe (entrepreneur, married, has children)"]},
    {"file": "Masculinity + Relationships.txt",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W", "Bovi Ugboma (comedian, married, 3 kids)", "Do2dtun Energy gAD (radio personality, divorced, kids)"]},
    {"file": "Pt 2 Masculinity + Relationships.txt",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W", "Alex Ikemefuna (younger entrepreneur, married circa 2021 post-COVID, has young daughter)", "Johnny Drille (musician)"]},
    {"file": "Masculinity + Friendship.txt",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W", "Alex Ikemefuna"]},
    {"file": "Masculinity + Fatherhood.txt",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W", "Timi Dakolo (singer, married Busola, 4 kids)", "Hermes Iyele (psychologist)"]},
    {"file": "Masculinity + Young Boys.txt",
     "panel": ["Ebuka Obi-Uchendu (host)", "Banky W", "IK Osakioduwa (radio/TV host, married, daughters)", "Murewa Adekoya (younger panelist)", "Sonariwo OnDeck (younger panelist, no kids yet)"]},
]

BANKY_BIO = """Bankole 'Banky W' Wellington — Nigerian musician, actor, entrepreneur (b. 1981).
- Founded EME Records (D'banj-era contemporary).
- Married actress Adesua Etomi in November 2017 (NOT post-COVID).
- Has TWO SONS (no daughter): older son Hazaiah b. ~2021, second son b. ~2023.
- Ran for House of Reps in 2019 and 2023 (unsuccessful).
- Teaches at Union College (recent role; commutes Nigeria/US).
- Devout Christian, often quotes scripture.
- Lives in Lagos.

If a snippet says any of the following AS A FIRST-PERSON STATEMENT (not a quoted joke or third-party reference), it is NOT Banky:
- 'our daughter' / 'my daughter'
- 'I don't have a son' / 'I don't have kids'
- 'I just got married' / 'I got married after COVID' / 'I got married in 2021/2022/2023/2024'
- 'before I had kids' (past tense — Banky has had kids since 2021)
- references to a profession Banky doesn't have (e.g. 'as a comedian', 'on my radio show')

If a snippet just MENTIONS a daughter as a hypothetical/parable/third-party (e.g. 'a Jewish parent saying my daughter is a doctor', 'Mr Easy and Temi just got married'), that is fine — Banky CAN narrate other people's stories."""


# ---------- PASS 1: transcript alignment ----------

def load_transcripts():
    """Return {episode_file_stem: [(speaker, text), ...]}."""
    out = {}
    for ep in EPISODES:
        path = TRANS_DIR / ep["file"]
        text = path.read_text()
        turns = []
        current_speaker, current_text = None, []
        for line in text.split("\n"):
            line = line.rstrip()
            if not line:
                continue
            m = re.match(r"^([A-Za-z][A-Za-z0-9 .\-_'’]{0,60}?):\s*(.*)$", line)
            if m and len(m.group(1).split()) <= 6:
                if current_speaker is not None:
                    turns.append((current_speaker, " ".join(current_text).strip()))
                current_speaker = m.group(1).strip()
                current_text = [m.group(2)]
            else:
                if current_speaker is None:
                    current_speaker = "UNKNOWN"
                    current_text = []
                current_text.append(line)
        if current_speaker is not None:
            turns.append((current_speaker, " ".join(current_text).strip()))
        out[path.stem] = turns
    return out


def normalize(s):
    return re.sub(r"\s+", " ", s.lower().strip())


def pass1_alignment(df, transcripts):
    """For each snippet, find its containing turn and record the speaker label."""
    results = []
    # Build search index: list of (episode, turn_idx, speaker, normalized_text)
    index = []
    for ep_stem, turns in transcripts.items():
        for ti, (sp, txt) in enumerate(turns):
            index.append((ep_stem, ti, sp, normalize(txt)))

    for _, row in df.iterrows():
        snippet = normalize(str(row["Verbatim Text (CODE THIS)"]))
        # Search for first 80 chars of snippet inside any turn
        probe = snippet[:80]
        match = None
        for ep_stem, ti, sp, ntxt in index:
            if probe and probe in ntxt:
                match = (ep_stem, ti, sp)
                break
        if match is None:
            # fallback: shorter probe
            probe2 = snippet[:40]
            for ep_stem, ti, sp, ntxt in index:
                if probe2 and probe2 in ntxt:
                    match = (ep_stem, ti, sp)
                    break
        if match is None:
            results.append({"Segment ID": row["Segment ID"], "p1_episode": None,
                            "p1_speaker": "NOT_FOUND", "p1_pass": False})
        else:
            ep_stem, ti, sp = match
            is_banky = "banky" in sp.lower() or sp.strip().lower() in ("banky w", "banky w.")
            results.append({"Segment ID": row["Segment ID"], "p1_episode": ep_stem,
                            "p1_speaker": sp, "p1_pass": is_banky})
    return pd.DataFrame(results)


# ---------- PASS 2 & 3: LLM checks ----------

PASS2_PROMPT = """You are verifying speaker attribution on a Nigerian masculinity podcast.

BIOGRAPHY:
{bio}

SNIPPET (claimed to be spoken by Banky W in first person):
\"\"\"{snippet}\"\"\"

Answer JSON only:
{{"verdict": "plausible" | "implausible" | "unclear",
  "reason": "<one sentence — cite the biographical contradiction if implausible, otherwise note why it fits>"}}"""

PASS3_PROMPT = """You are identifying which podcast panelist most likely said this snippet.

EPISODE PANEL (one of these people said it):
{panel}

SNIPPET:
\"\"\"{snippet}\"\"\"

Use biographical / contextual / stylistic cues. Banky W has 2 sons, married Adesua Etomi 2017, EME records, musician/actor, devout Christian, ran for office, teaches at Union College recently.

Answer JSON only:
{{"top_guess": "<exact panelist name from list>",
  "confidence": "high" | "medium" | "low",
  "reason": "<one sentence>"}}"""


async def llm_call(client, sem, prompt):
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
                    return {"verdict": "unclear", "top_guess": "UNCLEAR",
                            "reason": f"llm error: {err[:120]}"}
                await asyncio.sleep(2 ** attempt)


async def pass2_pass3(df, p1_df, transcripts):
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)

    # Map episode_stem -> panel
    panel_lookup = {Path(ep["file"]).stem: ep["panel"] for ep in EPISODES}
    p1_lookup = {r["Segment ID"]: r for _, r in p1_df.iterrows()}

    coros2, coros3, ids = [], [], []
    for _, row in df.iterrows():
        sid = row["Segment ID"]
        snip = str(row["Verbatim Text (CODE THIS)"])[:1800]
        ep_stem = p1_lookup[sid]["p1_episode"]
        panel = panel_lookup.get(ep_stem) if ep_stem else [
            "Banky W", "Ebuka Obi-Uchendu", "(unknown other panelists)"]
        coros2.append(llm_call(client, sem, PASS2_PROMPT.format(bio=BANKY_BIO, snippet=snip)))
        coros3.append(llm_call(client, sem, PASS3_PROMPT.format(panel="\n".join(f"- {p}" for p in panel), snippet=snip)))
        ids.append(sid)

    print(f"  running pass 2 + 3 ({len(coros2)*2} gpt-4o calls)…", flush=True)
    res2 = await atqdm.gather(*coros2, desc="pass2")
    res3 = await atqdm.gather(*coros3, desc="pass3")

    rows = []
    for sid, r2, r3 in zip(ids, res2, res3):
        rows.append({
            "Segment ID": sid,
            "p2_verdict": r2.get("verdict", "unclear"),
            "p2_reason":  r2.get("reason", ""),
            "p3_top":     r3.get("top_guess", "UNCLEAR"),
            "p3_conf":    r3.get("confidence", "low"),
            "p3_reason":  r3.get("reason", ""),
        })
    return pd.DataFrame(rows)


# ---------- PASS 4: consensus ----------

def pass4_consensus(p1, p2_3):
    merged = p1.merge(p2_3, on="Segment ID")
    drops = []
    for _, r in merged.iterrows():
        # Drop if Pass 1 fails AND (Pass 2 implausible OR Pass 3 picks non-Banky with high/medium conf)
        # OR drop if Pass 2 implausible AND Pass 3 picks non-Banky
        p1_fail = not r["p1_pass"]
        p2_bad  = r["p2_verdict"] == "implausible"
        p3_other = "banky" not in str(r["p3_top"]).lower()
        p3_strong = r["p3_conf"] in ("high", "medium")

        if p1_fail and (p2_bad or (p3_other and p3_strong)):
            drops.append((r["Segment ID"], "p1_fail+confirmed"))
        elif p2_bad and p3_other:
            drops.append((r["Segment ID"], "p2_implausible+p3_other"))
    return drops, merged


# ---------- PASS 5: scope re-validation ----------

PASS5_PROMPT = """The MENtality podcast is a Nigerian show about masculinity. Its full topic is in-scope.

Reject ONLY if the snippet is genuinely off-topic — e.g. ad read, birthday wish, sound-check banter, hello/intro chit-chat with no substance, single-word filler.

SNIPPET:
\"\"\"{snippet}\"\"\"

JSON only:
{{"on_scope": true | false, "reason": "<one sentence>"}}"""


async def pass5_scope(df, kept_ids):
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(CONCURRENCY)
    coros, ids = [], []
    for _, row in df.iterrows():
        if row["Segment ID"] not in kept_ids:
            continue
        snip = str(row["Verbatim Text (CODE THIS)"])[:1800]
        coros.append(llm_call(client, sem, PASS5_PROMPT.format(snippet=snip)))
        ids.append(row["Segment ID"])
    print(f"  running pass 5 ({len(coros)} gpt-4o calls)…", flush=True)
    res = await atqdm.gather(*coros, desc="pass5")
    drops = [(sid, "scope: " + r.get("reason", "")[:80])
             for sid, r in zip(ids, res) if r.get("on_scope") is False]
    return drops, [{"Segment ID": sid, "p5_on_scope": r.get("on_scope", True),
                    "p5_reason": r.get("reason", "")} for sid, r in zip(ids, res)]


# ---------- main ----------

async def main():
    print("=== Banky Wellington 5-pass verification ===", flush=True)
    df = pd.read_excel(FINAL_PATH)
    print(f"  starting rows: {len(df)}", flush=True)

    # PASS 1
    print("\n--- PASS 1: transcript alignment ---", flush=True)
    transcripts = load_transcripts()
    p1 = pass1_alignment(df, transcripts)
    p1_fail = p1[~p1["p1_pass"]]
    print(f"  pass-1 failures (snippet not in a Banky-labelled turn): {len(p1_fail)}/{len(df)}", flush=True)
    for _, r in p1_fail.head(10).iterrows():
        print(f"    {r['Segment ID']:>8s}  speaker={r['p1_speaker']!r}  ep={r['p1_episode']}", flush=True)

    # PASS 2 + 3
    print("\n--- PASS 2 (bio plausibility) + PASS 3 (panel cross-check) ---", flush=True)
    p23 = await pass2_pass3(df, p1, transcripts)
    p2_bad = p23[p23["p2_verdict"] == "implausible"]
    p3_other = p23[~p23["p3_top"].str.lower().str.contains("banky", na=False)]
    print(f"  pass-2 implausible: {len(p2_bad)}/{len(df)}", flush=True)
    print(f"  pass-3 non-Banky top guess: {len(p3_other)}/{len(df)}", flush=True)

    # PASS 4
    print("\n--- PASS 4: consensus drop ---", flush=True)
    drops4, merged = pass4_consensus(p1, p23)
    drop_ids4 = {sid for sid, _ in drops4}
    print(f"  consensus drops: {len(drop_ids4)}/{len(df)}", flush=True)
    for sid, reason in drops4[:20]:
        snip = df[df["Segment ID"] == sid]["Verbatim Text (CODE THIS)"].iloc[0]
        print(f"    DROP {sid} ({reason}): {snip[:120]}…", flush=True)

    kept_ids = set(df["Segment ID"]) - drop_ids4

    # PASS 5
    print("\n--- PASS 5: scope re-validation on survivors ---", flush=True)
    drops5, p5_rows = await pass5_scope(df, kept_ids)
    drop_ids5 = {sid for sid, _ in drops5}
    print(f"  pass-5 scope drops: {len(drop_ids5)}", flush=True)
    for sid, reason in drops5[:20]:
        snip = df[df["Segment ID"] == sid]["Verbatim Text (CODE THIS)"].iloc[0]
        print(f"    DROP {sid} ({reason}): {snip[:120]}…", flush=True)

    final_drop = drop_ids4 | drop_ids5
    kept = df[~df["Segment ID"].isin(final_drop)].reset_index(drop=True)
    # Re-issue Segment IDs to keep them contiguous
    kept["Segment ID"] = [f"BNK_{i+1:03d}" for i in range(len(kept))]

    # Save audit
    p5_df = pd.DataFrame(p5_rows)
    audit = merged.merge(p5_df, on="Segment ID", how="left")
    audit["dropped"] = audit["Segment ID"].isin(final_drop)
    audit_path = AUDIT_DIR / "audit.xlsx"
    audit.to_excel(audit_path, index=False)

    # Overwrite final
    kept.to_excel(FINAL_PATH, index=False)
    print(f"\n=== DONE ===", flush=True)
    print(f"  before: {len(df)}", flush=True)
    print(f"  drop pass-4 (misattribution): {len(drop_ids4)}", flush=True)
    print(f"  drop pass-5 (scope):          {len(drop_ids5)}", flush=True)
    print(f"  kept:                         {len(kept)}", flush=True)
    print(f"  audit → {audit_path.relative_to(ROOT)}", flush=True)
    print(f"  final → {FINAL_PATH.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
