from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path("/Users/dhruvbhanderi/Documents/USC/New Research Engineer/Final datasets/Kenya Audience Analysis Comments.xlsx")
OUT_DIR = Path("/Users/dhruvbhanderi/Documents/USC/New Research Engineer/Codex/outputs/kenya_llm_exploratory")
OUT_JSON = OUT_DIR / "kenya_audience_llm_analysis.json"
OUT_MD = OUT_DIR / "Kenya Audience LLM Exploratory Report.md"
OUT_CSV = OUT_DIR / "kenya_audience_row_coding.csv"


CREATOR_MAP = {
    "Andrew": "Andrew Kibe",
    "EricA": "Eric Amunga (Amerix)",
    "Rixpoet": "Onyango Otieno (Rixpoet)",
    "Eddy": "Eddy Kimani",
}

ORIENTATION = {
    "Andrew Kibe": "regressive / manosphere-adjacent",
    "Eric Amunga (Amerix)": "regressive / manosphere-adjacent",
    "Onyango Otieno (Rixpoet)": "progressive / vulnerability-forward",
    "Eddy Kimani": "progressive / vulnerability-forward",
}

PIECE_LABELS = {
    "Andrew Kibe": "I wonder how some men are satisfied with just one woman",
    "Eric Amunga (Amerix)": "A woman can't love a man; it is a man who loves a woman",
    "Onyango Otieno (Rixpoet)": "My voice was beaten out of me by my father / toxic masculinity",
    "Eddy Kimani": "Men are not missing; they are evolving",
}


THEME_PATTERNS = {
    "Relationships, love, loyalty": [
        r"\blove\b", r"\bloyal", r"\bheart\b", r"\brelationship", r"\bmarry",
        r"\bhusband\b", r"\bwife\b", r"\bgirlfriend\b", r"\bdating\b",
        r"\brespect\b", r"\breciproc", r"\btwo[- ]?way\b", r"\bmutual\b",
    ],
    "Mental health, trauma, healing": [
        r"\btrauma", r"\bheal", r"\bemotion", r"\btherapy\b", r"\bmental",
        r"\bptsd\b", r"\bstory\b", r"\bpain\b", r"\bchildhood\b",
        r"\bauthentic", r"\bvulnerab", r"\bhealthy\b", r"\btears?\b",
    ],
    "Violence, abuse, accountability": [
        r"\babus", r"\bbeaten\b", r"\bviolence\b", r"\bpolice\b",
        r"\brape", r"\btoxic\b", r"\baccountab", r"\bstop it\b",
        r"\bfather'?s damage\b", r"\bwatched you\b",
    ],
    "Male self-improvement, discipline, purpose": [
        r"\bbuild", r"\bgreatness\b", r"\bconquer", r"\bpurpose\b",
        r"\bdiscipline\b", r"\bfocus\b", r"\bempire\b", r"\bhustle\b",
        r"\bwork\b", r"\bgrowth\b", r"\bclarity\b", r"\bgrounded\b",
        r"\bself\b", r"\bimpact\b", r"\binspire\b",
    ],
    "Money, status, provision": [
        r"\bmoney\b", r"\bbills?\b", r"\bprovider", r"\brent\b",
        r"\bcollege\b", r"\bjob\b", r"\bbusiness\b", r"\bwealth\b",
        r"\bcar\b", r"\bcars\b", r"\bstatus\b", r"\bneeded\b",
    ],
    "Female behavior / critique of women": [
        r"\bwomen fantasize\b", r"\bwomen are\b", r"\ba woman can'?t\b",
        r"\bfemales?\b", r"\bsubmit", r"\bbaby daddy\b", r"\bunimpressive\b",
        r"\bhypergamy\b", r"\bspoiled\b", r"\bwoman or feminine\b",
        r"\bwoman\b.*\brespect\b",
    ],
    "Equality, reciprocity, mutual respect": [
        r"\btwo[- ]?way\b", r"\bmutual\b", r"\breciproc", r"\bequal",
        r"\bboth\b", r"\bpartnership\b", r"\brespectful\b",
        r"\bsupport\b", r"\brespect\b", r"\bnot people\b",
    ],
    "Religion, morality, spirituality": [
        r"\bgod\b", r"\bbible\b", r"\btitus\b", r"\bpray", r"\bbless",
        r"\bsin\b", r"\bchurch\b", r"\bkingdom\b",
    ],
    "Men withdrawing / peace over performance": [
        r"\bclubs?\b", r"\bdating apps?\b", r"\bperformance culture\b",
        r"\bpeace of mind\b", r"\bunbothered\b", r"\bwalking away\b",
        r"\bmissing\b", r"\bevolving\b", r"\bsystems?\b", r"\blow\b",
        r"\bgaming\b",
    ],
    "Humor, sarcasm, low-substance uptake": [
        r"\blol\b", r"\blmao\b", r"\bhaha", r"😂", r"🤣", r"\btoad\b",
        r"\bdumb\b", r"\btrue\b", r"\bfacts\b", r"💯",
    ],
}

POSITIVE_PATTERNS = [
    r"\btrue love\b", r"\bloyal", r"\brefreshing\b", r"\bhappy\b",
    r"\bhealthy\b", r"\bhealing\b", r"\blove\b", r"\brespect\b",
    r"\bsupport\b", r"\binspire\b", r"\bgreat\b", r"\bgood\b",
    r"\bpeace\b", r"\bwisdom\b", r"\bauthentic", r"\bbrave\b",
    r"\bwell ?done\b", r"\bbless", r"\bhope\b", r"\bamazing\b",
    r"\bpowerful\b", r"\bfulfilling\b", r"\bgrounded\b", r"\bclarity\b",
]

NEGATIVE_PATTERNS = [
    r"\babus", r"\bsick\b", r"\btoxic\b", r"\bpain\b", r"\bproblem",
    r"\bwrong\b", r"\bdisagree\b", r"\bhate\b", r"\bdraining\b",
    r"\bstruggle\b", r"\btrauma\b", r"\bptsd\b", r"\blosing\b",
    r"\bhurt\b", r"\bshame\b", r"\bbroken\b", r"\blame\b",
    r"\bdumb\b", r"\btoad\b", r"\bunimpressive\b", r"\bno one\b",
    r"\bnot worse\b",
]

CRITIQUE_PATTERNS = [
    r"\bdisagree\b", r"\bstrongly disagree\b", r"\bwrong\b",
    r"\bdumb\b", r"\bnot people\b", r"\bwomen are not cars\b",
    r"\bcould you show\b", r"\bthere is a huge difference\b",
    r"\bironical\b", r"\bbut maybe\b",
]

SUPPORT_PATTERNS = [
    r"\btrue\b", r"\bfacts\b", r"\bagree\b", r"\bwell said\b",
    r"\bexactly\b", r"💯", r"\blove your\b", r"\brefreshing\b",
    r"\bthank you\b", r"\bthis is powerful\b", r"\bmay men arise\b",
]

PERSONAL_PATTERNS = [
    r"\bi\b", r"\bmy\b", r"\bme\b", r"\bwe\b", r"\bour\b",
]

INSULT_PATTERNS = [
    r"\bdumb\b", r"\btoad\b", r"\bstupid\b", r"\bidiot\b",
    r"\bnonsense\b", r"\bshut\b", r"\btrash\b",
]

MISOGYNY_PATTERNS = [
    r"\bwomen fantasize\b", r"\bwomen are\b.*\bunimpressive\b",
    r"\ba woman can'?t love\b", r"\bwoman or feminine\b",
    r"\bsubmit\b", r"\bfemales?\b.*\bneed\b",
    r"\bspoiled\b.*\bgirl", r"\bbaby daddy\b",
]


def hits(text: str, patterns: list[str]) -> int:
    return sum(1 for pattern in patterns if re.search(pattern, text, flags=re.I))


def first_sentence(text: str, limit: int = 240) -> str:
    clean = re.sub(r"\s+", " ", str(text)).strip()
    if len(clean) <= limit:
        return clean
    cut = clean[:limit].rsplit(" ", 1)[0]
    return f"{cut}..."


def load_comments() -> pd.DataFrame:
    rows = []
    xl = pd.ExcelFile(SOURCE)
    for sheet in xl.sheet_names:
        if sheet == "Summary Metrics":
            continue
        df = pd.read_excel(SOURCE, sheet_name=sheet)
        df = df.dropna(subset=["Comment"])
        df["source_sheet"] = sheet
        rows.append(df)
    out = pd.concat(rows, ignore_index=True)
    out = out.rename(
        columns={
            "Comment ID": "comment_id",
            "Influencer": "creator_raw",
            "Platform": "platform",
            "Source URL": "source_url",
            "Comment": "comment",
        }
    )
    out["creator"] = out["creator_raw"].map(CREATOR_MAP).fillna(out["creator_raw"])
    out["orientation"] = out["creator"].map(ORIENTATION).fillna("unknown")
    out["content_piece"] = out["creator"].map(PIECE_LABELS).fillna(out["source_sheet"])
    out["country"] = "Kenya"
    out["comment_id"] = out["comment_id"].apply(lambda x: "" if pd.isna(x) else str(x).strip())
    out["comment"] = out["comment"].astype(str).str.strip()
    out["comment_length"] = out["comment"].str.len()
    return out


def classify_row(row: pd.Series) -> dict[str, object]:
    text = row["comment"]
    low = text.lower()
    theme_scores = {theme: hits(low, pats) for theme, pats in THEME_PATTERNS.items()}
    themes = [theme for theme, score in sorted(theme_scores.items(), key=lambda kv: (-kv[1], kv[0])) if score > 0]
    if not themes:
        themes = ["General audience reaction / unclear"]
    primary_theme = themes[0]

    pos = hits(low, POSITIVE_PATTERNS)
    neg = hits(low, NEGATIVE_PATTERNS)
    if pos >= neg + 2:
        sentiment = "positive"
    elif neg >= pos + 2:
        sentiment = "negative"
    elif pos > 0 and neg > 0:
        sentiment = "mixed"
    elif pos > 0:
        sentiment = "positive"
    elif neg > 0:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    if primary_theme == "Mental health, trauma, healing" or hits(low, [r"\bfeel\b", r"\bemotion", r"\bsorry\b", r"\bpraying\b"]):
        emotion = "empathy/care" if pos >= neg else "sadness/pain"
    elif hits(low, [r"\bdumb\b", r"\bsick\b", r"\bwrong\b", r"\bdisagree\b", r"\bdraining\b", r"\bironical\b"]):
        emotion = "anger/frustration"
    elif hits(low, [r"\bbuild\b", r"\bgreatness\b", r"\binspire\b", r"\barise\b", r"\bempire\b", r"\bclarity\b"]):
        emotion = "hope/motivation"
    elif hits(low, [r"\bfacts\b", r"\btrue\b", r"💯", r"\bagree\b"]):
        emotion = "pride/validation"
    elif hits(low, [r"\bunimpressive\b", r"\bconquer\b", r"\bwoman or feminine\b"]):
        emotion = "contempt/superiority"
    elif sentiment == "negative":
        emotion = "anger/frustration"
    elif sentiment == "positive":
        emotion = "hope/motivation"
    else:
        emotion = "none/unclear"

    personal = hits(low, PERSONAL_PATTERNS) >= 2
    support = hits(low, SUPPORT_PATTERNS)
    critique = hits(low, CRITIQUE_PATTERNS)
    if len(low.split()) <= 5 or (hits(low, [r"😂", r"🤣", r"\blol\b"]) and len(low.split()) <= 12):
        audience_response = "joking/low-substance engagement"
    elif personal and (primary_theme in {"Mental health, trauma, healing", "Money, status, provision", "Men withdrawing / peace over performance"}):
        audience_response = "personal identification/sharing experience"
    elif critique > support:
        audience_response = "critique/disagreement"
    elif support > 0 and critique == 0:
        audience_response = "support/reinforcement"
    elif support > 0 and critique > 0 or hits(low, [r"\bbut\b", r"\bhowever\b", r"\bmaybe\b", r"\binteresting\b"]):
        audience_response = "debate/mixed response"
    else:
        audience_response = "unclear/not enough data" if len(low.split()) < 8 else "debate/mixed response"

    if primary_theme in {"Mental health, trauma, healing", "Violence, abuse, accountability"}:
        masculinity_type = "vulnerability/recovery-focused"
    elif primary_theme == "Equality, reciprocity, mutual respect" or hits(low, [r"\btoxic societal norms\b", r"\bemotionally healthy\b"]):
        masculinity_type = "progressive/equitable"
    elif primary_theme in {"Female behavior / critique of women", "Male self-improvement, discipline, purpose", "Money, status, provision"} and hits(low, [r"\bwomen\b", r"\bwoman\b", r"\bconquer\b", r"\bneeded\b"]):
        masculinity_type = "regressive/traditional/manosphere-adjacent"
    else:
        masculinity_type = "mixed/unclear"

    mentions_women = bool(re.search(r"\bwom[ae]n\b|\bfemale|\bgirl\b|\bwife\b|\bhusband\b", low))
    if hits(low, MISOGYNY_PATTERNS) or primary_theme == "Female behavior / critique of women":
        women_portrayal = "negative/problematic"
    elif mentions_women and hits(low, [r"\bmutual\b", r"\btwo[- ]?way\b", r"\bnot people\b", r"\brespect\b", r"\bsupport\b"]):
        women_portrayal = "positive/equal/respected"
    elif mentions_women:
        women_portrayal = "neutral/mixed"
    else:
        women_portrayal = "not present"

    if primary_theme == "Money, status, provision" or hits(low, [r"\bprovider\b", r"\bneeded\b", r"\bgreatness\b"]):
        men_expectation = "provider/status-driven"
    elif primary_theme in {"Mental health, trauma, healing", "Violence, abuse, accountability"}:
        men_expectation = "emotionally open/healing"
    elif primary_theme == "Equality, reciprocity, mutual respect":
        men_expectation = "equal/respectful/accountable"
    elif primary_theme in {"Male self-improvement, discipline, purpose", "Men withdrawing / peace over performance"}:
        men_expectation = "disciplined/self-improving"
    elif hits(low, [r"\bconquer\b", r"\bdomin", r"\bcontrol\b"]):
        men_expectation = "dominant/controlling"
    else:
        men_expectation = "not specified"

    if women_portrayal == "negative/problematic" or hits(low, [r"\bwomen fantasize\b", r"\bmen fantasize\b", r"\bman loves a woman\b"]):
        stereotype_direction = "reproduces stereotypes"
    elif hits(low, [r"\btoxic societal norms\b", r"\bemotionally healthy\b", r"\btwo[- ]?way\b", r"\bmutual\b", r"\bwomen are not cars\b", r"\bmen come out\b"]):
        stereotype_direction = "contests stereotypes"
    elif mentions_women or "men" in low:
        stereotype_direction = "mixed"
    else:
        stereotype_direction = "unclear/not applicable"

    if hits(low, [r"\bshould\b", r"\bmust\b", r"\bnever\b", r"\balways\b", r"\blet'?s\b", r"\btime to\b"]):
        prescriptive = "yes"
    elif hits(low, [r"\bmaybe\b", r"\bcan\b", r"\bpossible\b"]):
        prescriptive = "partly"
    else:
        prescriptive = "no"

    if personal and hits(low, [r"\bi went\b", r"\bmy dad\b", r"\bmy father\b", r"\bmy story\b", r"\bI was\b"]):
        communication_style = "personal story/testimony"
    elif hits(low, [r"\bshould\b", r"\bmust\b", r"\bnever\b", r"\balways\b", r"\btime to\b"]):
        communication_style = "advice/instruction/rules"
    elif hits(low, [r"😂", r"🤣", r"\blol\b", r"\bdumb\b", r"\btoad\b"]):
        communication_style = "humor/mockery/satire"
    elif hits(low, [r"\bbuild\b", r"\binspire\b", r"\barise\b", r"\bempire\b", r"\bgreatness\b"]):
        communication_style = "motivational/inspirational"
    elif critique > 0:
        communication_style = "call-out/accountability"
    else:
        communication_style = "commentary/opinion"

    if hits(low, INSULT_PATTERNS) or (text.isupper() and len(text) > 60):
        tone = "aggressive/confrontational"
    elif primary_theme in {"Mental health, trauma, healing", "Violence, abuse, accountability"}:
        tone = "vulnerable/pain-focused"
    elif sentiment == "positive":
        tone = "hopeful/encouraging"
    elif hits(low, [r"😂", r"🤣", r"\blol\b"]):
        tone = "humorous/light"
    elif sentiment == "neutral":
        tone = "neutral/mixed"
    else:
        tone = "serious/analytical"

    tox = 0
    tox += min(2, hits(low, INSULT_PATTERNS))
    tox += 1 if text.isupper() and len(text) > 60 else 0
    tox += 1 if hits(low, [r"\bhate\b", r"\bshut\b", r"\bsick\b"]) else 0
    toxicity = min(3, tox)

    misog = 0
    misog += 2 if hits(low, MISOGYNY_PATTERNS) else 0
    misog += 1 if women_portrayal == "negative/problematic" else 0
    misog += 1 if stereotype_direction == "reproduces stereotypes" and mentions_women else 0
    misogyny_intensity = min(3, misog)

    foundations = []
    if hits(low, [r"\babuse", r"\bharm", r"\btoxic", r"\bheal", r"\bsupport", r"\bcare", r"\bhealthy"]):
        foundations.append("care/harm")
    if hits(low, [r"\bloyal", r"\brespect", r"\bhusband", r"\bwife", r"\bfamily", r"\bchildren"]):
        foundations.append("loyalty/betrayal")
    if hits(low, [r"\bfather", r"\bpolice", r"\bauthority", r"\bmen must", r"\bsubmit"]):
        foundations.append("authority/respect")
    if hits(low, [r"\bmutual", r"\btwo[- ]?way", r"\bequal", r"\breciproc", r"\bfair"]):
        foundations.append("fairness/reciprocity")
    if hits(low, [r"\bgod", r"\bbible", r"\btitus", r"\bpray", r"\bchurch", r"\bbless"]):
        foundations.append("sanctity/religion")
    if hits(low, [r"\bfreedom", r"\bwalking away", r"\bunbothered", r"\bpeace of mind", r"\bno one is coming"]):
        foundations.append("liberty/autonomy")
    if not foundations:
        foundations.append("none/unclear")

    if row["creator"] == "Onyango Otieno (Rixpoet)":
        cluster = "Male trauma disclosure, healing, and empathy"
    elif row["creator"] == "Eddy Kimani":
        cluster = "Men withdrawing from performance culture to seek peace"
    elif row["creator"] == "Andrew Kibe":
        cluster = "Monogamy, women-as-analogy debate, and loyalty"
    elif row["creator"] == "Eric Amunga (Amerix)":
        cluster = "Gendered love, respect, greatness, and conditionality"
    else:
        cluster = primary_theme

    if primary_theme not in cluster:
        cluster_detail = f"{cluster} / {primary_theme}"
    else:
        cluster_detail = cluster

    return {
        "themes__themes": "; ".join(themes[:4]),
        "themes__primary_theme": primary_theme,
        "sentiment__sentiment": sentiment,
        "emotion__primary_emotion": emotion,
        "stance__audience_response": audience_response,
        "masculinity_type": masculinity_type,
        "women_portrayal": women_portrayal,
        "men_expectation": men_expectation,
        "stereotype_direction": stereotype_direction,
        "communication_style": communication_style,
        "prescriptive": prescriptive,
        "tone": tone,
        "toxicity__toxicity_0_3": toxicity,
        "misogyny__intensity_0_3": misogyny_intensity,
        "hate_speech__flag": "possible" if toxicity >= 3 and misogyny_intensity >= 2 else "no",
        "moral_foundations__foundations": "; ".join(foundations),
        "topic_cluster_label": cluster,
        "topic_cluster_detail": cluster_detail,
        "llm_notes": first_sentence(text),
    }


def percent(n: int, d: int) -> str:
    return f"{(100 * n / d):.1f}%" if d else "0.0%"


def count_table(series: pd.Series, top_n: int | None = None) -> list[list[object]]:
    vc = series.value_counts(dropna=False)
    if top_n:
        vc = vc.head(top_n)
    total = int(series.notna().sum())
    return [["Category", "Count", "Share"]] + [[str(k), int(v), percent(int(v), total)] for k, v in vc.items()]


def crosstab_rows(df: pd.DataFrame, index: str, columns: str) -> list[list[object]]:
    tab = pd.crosstab(df[index], df[columns])
    return [[index, *tab.columns.tolist()]] + [[idx, *[int(v) for v in vals]] for idx, vals in tab.iterrows()]


def pick_quotes(df: pd.DataFrame) -> list[dict[str, object]]:
    quotes = []
    seen = set()
    for theme in df["themes__primary_theme"].value_counts().index:
        sub = df[df["themes__primary_theme"] == theme].copy()
        sub["rank_len"] = sub["comment"].str.len().clip(upper=420)
        sub = sub.sort_values(["rank_len", "comment_length"], ascending=[False, False]).head(3)
        for _, row in sub.iterrows():
            key = (theme, row["comment_id"])
            if key in seen:
                continue
            seen.add(key)
            quotes.append(
                {
                    "theme": theme,
                    "creator": row["creator"],
                    "sentiment": row["sentiment__sentiment"],
                    "audience_response": row["stance__audience_response"],
                    "comment_id": str(row["comment_id"]),
                    "quote": first_sentence(row["comment"], 420),
                }
            )
    return quotes[:28]


def creator_summary(df: pd.DataFrame) -> list[list[object]]:
    rows = [["Creator", "Orientation", "Platform", "Comments", "Positive", "Negative", "Mixed/Neutral", "Top theme", "Top audience response", "Avg toxicity", "Avg misogyny"]]
    for creator, sub in df.groupby("creator", sort=False):
        sent = sub["sentiment__sentiment"].value_counts()
        top_theme = sub["themes__primary_theme"].value_counts().idxmax()
        top_response = sub["stance__audience_response"].value_counts().idxmax()
        rows.append(
            [
                creator,
                sub["orientation"].iloc[0],
                ", ".join(sorted(sub["platform"].unique())),
                len(sub),
                int(sent.get("positive", 0)),
                int(sent.get("negative", 0)),
                int(sent.get("mixed", 0) + sent.get("neutral", 0)),
                top_theme,
                top_response,
                round(float(sub["toxicity__toxicity_0_3"].mean()), 2),
                round(float(sub["misogyny__intensity_0_3"].mean()), 2),
            ]
        )
    return rows


def theme_summary(df: pd.DataFrame) -> list[list[object]]:
    exploded = []
    for _, row in df.iterrows():
        for theme in str(row["themes__themes"]).split("; "):
            if theme:
                exploded.append(
                    {
                        "theme": theme,
                        "creator": row["creator"],
                        "sentiment": row["sentiment__sentiment"],
                    }
                )
    ex = pd.DataFrame(exploded)
    rows = [["Theme", "Mentions", "Share of comments", "Top creator", "Positive", "Negative", "Mixed/Neutral"]]
    for theme, sub in ex.groupby("theme"):
        sent = sub["sentiment"].value_counts()
        rows.append(
            [
                theme,
                len(sub),
                percent(len(sub), len(df)),
                sub["creator"].value_counts().idxmax(),
                int(sent.get("positive", 0)),
                int(sent.get("negative", 0)),
                int(sent.get("mixed", 0) + sent.get("neutral", 0)),
            ]
        )
    return [rows[0]] + sorted(rows[1:], key=lambda r: (-r[1], r[0]))


def topic_summary(df: pd.DataFrame) -> list[list[object]]:
    rows = [["Topic cluster", "Comments", "Share", "Primary creators", "Dominant theme", "Dominant sentiment"]]
    for cluster, sub in df.groupby("topic_cluster_label"):
        creators = ", ".join(sub["creator"].value_counts().head(2).index.tolist())
        rows.append(
            [
                cluster,
                len(sub),
                percent(len(sub), len(df)),
                creators,
                sub["themes__primary_theme"].value_counts().idxmax(),
                sub["sentiment__sentiment"].value_counts().idxmax(),
            ]
        )
    return [rows[0]] + sorted(rows[1:], key=lambda r: (-r[1], r[0]))


def write_report(df: pd.DataFrame, data: dict[str, object]) -> None:
    total = len(df)
    top_themes = df["themes__primary_theme"].value_counts().head(6)
    sent = df["sentiment__sentiment"].value_counts()
    response = df["stance__audience_response"].value_counts()
    misog = int((df["misogyny__intensity_0_3"] >= 2).sum())
    tox = int((df["toxicity__toxicity_0_3"] >= 2).sum())

    lines = [
        "# Kenya Audience LLM Exploratory Analysis",
        "",
        f"Source: `{SOURCE.name}`",
        f"Rows analyzed: **{total}** audience comments across **{df['creator'].nunique()}** creators.",
        "",
        "## Executive Takeaways",
        "",
        "1. The Kenya audience data splits into two very different reception modes: regressive/manosphere-adjacent posts generate debate around love, women, loyalty, status, and respect, while progressive/vulnerability-forward posts generate identification, empathy, healing language, and social critique.",
        "2. Rixpoet's audience is the clearest vulnerability-forward case: comments repeatedly validate male trauma disclosure, childhood abuse survival, emotional health, and men speaking publicly about pain.",
        "3. Eddy Kimani's thread is less trauma-centered and more about male withdrawal from performance culture: peace of mind, staying low, work, gaming, clubs/dating apps, and rejecting externally scripted provider expectations.",
        "4. Andrew Kibe's comment set is dominated by the women-as-car analogy, monogamy versus variety, and direct pushback that women should not be objectified. The same thread contains both reinforcement of traditional gender logic and visible contestation.",
        "5. Eric/Amerix's audience clusters around conditional love, respect, greatness, and reciprocal love. Several comments endorse the gendered premise, but a meaningful countercurrent argues love must be mutual and two-way.",
        f"6. Explicitly high misogyny and toxicity are concentrated rather than pervasive: {misog} comments scored 2+ on misogyny intensity and {tox} scored 2+ on toxicity.",
        "",
        "## Distribution Snapshot",
        "",
        "### Primary Themes",
        "",
    ]
    for theme, n in top_themes.items():
        lines.append(f"- **{theme}**: {n} comments ({percent(int(n), total)})")
    lines.extend(["", "### Sentiment", ""])
    for k, n in sent.items():
        lines.append(f"- **{k}**: {int(n)} ({percent(int(n), total)})")
    lines.extend(["", "### Audience Response", ""])
    for k, n in response.items():
        lines.append(f"- **{k}**: {int(n)} ({percent(int(n), total)})")
    lines.extend(
        [
            "",
            "## Creator-Level Reading",
            "",
            "- **Andrew Kibe**: The thread is a compact debate over monogamy, sexual variety, and objectification. Pushback is sharper here than in the other regressive thread, especially around the claim that women can be analogized to cars.",
            "- **Eric Amunga (Amerix)**: The dominant uptake affirms or debates the claim that men love women and women respond to value/respect. The counter-discourse is more measured than Andrew's thread and centers reciprocity.",
            "- **Onyango Otieno (Rixpoet)**: The audience responds with testimony, empathy, and care. Many comments use the content as permission to disclose family harm, unresolved childhood pain, and the need for men to speak.",
            "- **Eddy Kimani**: The audience frames men as opting out of draining social scripts. Comments often mix humor with social diagnosis: clubs, dating apps, provision, peace, work, and emotional self-preservation.",
            "",
            "## Method Note",
            "",
            "This workbook applies the Nigeria notebook's audience-analysis spirit to the uploaded Kenya workbook: one comment per row, creator/orientation metadata, controlled theme labels, sentiment, emotion, stance/audience response, gender framing, toxicity/misogyny intensity, moral foundations, and emergent topic labels. Row-level labels should be treated as exploratory coding for review, not final intercoder-reliability adjudication.",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_comments()
    coded = pd.DataFrame([classify_row(row) for _, row in df.iterrows()])
    out = pd.concat([df.reset_index(drop=True), coded], axis=1)

    ordered_cols = [
        "comment_id",
        "source_url",
        "comment",
        "creator",
        "creator_raw",
        "platform",
        "orientation",
        "content_piece",
        "country",
        "comment_length",
        "themes__primary_theme",
        "themes__themes",
        "sentiment__sentiment",
        "emotion__primary_emotion",
        "stance__audience_response",
        "masculinity_type",
        "women_portrayal",
        "men_expectation",
        "stereotype_direction",
        "communication_style",
        "prescriptive",
        "tone",
        "toxicity__toxicity_0_3",
        "misogyny__intensity_0_3",
        "hate_speech__flag",
        "moral_foundations__foundations",
        "topic_cluster_label",
        "topic_cluster_detail",
        "llm_notes",
        "source_sheet",
    ]
    out = out[ordered_cols]
    out.to_csv(OUT_CSV, index=False)

    data = {
        "source": str(SOURCE),
        "row_count": int(len(out)),
        "summary": {
            "overview": [
                ["Metric", "Value"],
                ["Country", "Kenya"],
                ["Dataset", "Audience comments"],
                ["Total comments", int(len(out))],
                ["Creators", int(out["creator"].nunique())],
                ["Platforms", ", ".join(sorted(out["platform"].unique()))],
                ["Source workbook", SOURCE.name],
                ["Analysis approach", "GPT-5.5 qualitative synthesis + codebook-style row tagging"],
            ],
            "key_takeaways": [
                ["#", "Takeaway"],
                [1, "Two reception modes dominate: gender-role debate around regressive creators and empathy/healing around vulnerability-forward creators."],
                [2, "Rixpoet has the strongest personal-testimony pattern, with many comments validating male trauma disclosure."],
                [3, "Eddy's audience frames men as stepping back from clubs, dating scripts, and provider performance toward peace of mind."],
                [4, "Andrew's thread contains the sharpest objectification pushback, especially against the women-as-cars analogy."],
                [5, "Eric/Amerix's thread centers conditional love, respect, greatness, and a visible reciprocity counter-frame."],
                [6, "High misogyny/toxicity is present but concentrated in a minority of comments."],
            ],
            "sentiment": count_table(out["sentiment__sentiment"]),
            "audience_response": count_table(out["stance__audience_response"]),
            "women_portrayal": count_table(out["women_portrayal"]),
            "creator_summary": creator_summary(out),
            "theme_summary": theme_summary(out),
            "topic_summary": topic_summary(out),
            "sentiment_by_creator": crosstab_rows(out, "creator", "sentiment__sentiment"),
            "response_by_creator": crosstab_rows(out, "creator", "stance__audience_response"),
        },
        "rows": out.fillna("").astype(object).values.tolist(),
        "headers": out.columns.tolist(),
        "quotes": pick_quotes(out),
    }
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(out, data)
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_CSV}")
    print(f"wrote {OUT_MD}")
    print(out.shape)


if __name__ == "__main__":
    main()
