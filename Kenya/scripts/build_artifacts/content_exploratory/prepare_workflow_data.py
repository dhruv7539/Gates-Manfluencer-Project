from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


BASE = Path("/Users/dhruvbhanderi/Documents/USC/New Research Engineer")
SOURCE_DIR = BASE / "Final datasets"
OUT_DIR = BASE / "Codex" / "outputs" / "kenya_two_pass_llm_workflow"
OUT_JSON = OUT_DIR / "kenya_two_pass_workflow_data.json"

SNIPPET_SOURCE = SOURCE_DIR / "Kenya Content Analysis Snippets.xlsx"
COMMENT_SOURCE = SOURCE_DIR / "Kenya Audience Analysis Comments.xlsx"

CONTENT_HUMAN_SOURCE = SOURCE_DIR / "Kenya_Content_Human_Coding_Top200_Balanced_Cleaned_English_Context.xlsx"
AUDIENCE_HUMAN_SOURCE = SOURCE_DIR / "Kenya_Audience_Human_Coding_Top200_Balanced_SourceURLs_Fixed.xlsx"
CONTENT_OVERLAP_SOURCE = SOURCE_DIR / "Kenya_Content_Overlap_Distribution_6Coders_StrictMostRelevant_v2.xlsx"
AUDIENCE_OVERLAP_SOURCE = SOURCE_DIR / "Kenya_Audience_Overlap_Distribution_6Coders_StrictMostRelevant.xlsx"


CONTENT_ORIENTATION = {
    "Eddy Kimani": "Progressive",
    "Onyango Otieno (Rixpoet)": "Progressive",
    "Philip Karanja": "Progressive",
    "Eric Amunga / Amerix": "Regressive",
    "Andrew Kibe": "Regressive",
}

COMMENT_CREATOR_MAP = {
    "Andrew": "Andrew Kibe",
    "EricA": "Eric Amunga / Amerix",
    "Rixpoet": "Onyango Otieno (Rixpoet)",
    "Eddy": "Eddy Kimani",
}

COMMENT_TARGETS = {
    "Andrew Kibe": "Original post asks why some men are satisfied with one woman; target claim concerns monogamy, sexual variety, and women's role in male satisfaction.",
    "Eric Amunga / Amerix": "Original post claims a woman cannot love a man in the same way a man loves a woman; target claim concerns gendered love, respect, and male greatness.",
    "Onyango Otieno (Rixpoet)": "Original post/testimony discusses a father's violence, male emotional suppression, and toxic masculinity; target claim concerns trauma and men's need to speak/heal.",
    "Eddy Kimani": "Original post argues men are not missing but evolving or withdrawing from social performance; target claim concerns men seeking peace, healing, and self-definition.",
}


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def as_str(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def maybe_url(value: object) -> str:
    text = as_str(value)
    return text if text.startswith("http://") or text.startswith("https://") else ""


def load_snippets() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    xl = pd.ExcelFile(SNIPPET_SOURCE)
    for sheet in xl.sheet_names:
        if sheet.lower().startswith("summary"):
            continue
        df = pd.read_excel(SNIPPET_SOURCE, sheet_name=sheet)
        id_col = "Tweet ID" if "Tweet ID" in df.columns else "Segment ID"
        for idx, row in df.iterrows():
            text = clean_text(row.get("Text"))
            if not text:
                continue
            influencer = as_str(row.get("Influencer"))
            context = clean_text(row.get("Context"))
            source_url = maybe_url(context)
            rows.append(
                {
                    "dataset_type": "snippet",
                    "country": "Kenya",
                    "item_id": as_str(row.get(id_col)),
                    "influencer": influencer,
                    "orientation": CONTENT_ORIENTATION.get(influencer, "Unclear"),
                    "platform": as_str(row.get("Platform")),
                    "content_type": as_str(row.get("Content Type")),
                    "source_url": source_url,
                    "context": context,
                    "text": text,
                    "word_count": len(text.split()),
                    "original_sheet": sheet,
                    "original_row": int(idx) + 2,
                }
            )
    return rows


def load_comments() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    xl = pd.ExcelFile(COMMENT_SOURCE)
    for sheet in xl.sheet_names:
        if sheet.lower().startswith("summary"):
            continue
        df = pd.read_excel(COMMENT_SOURCE, sheet_name=sheet)
        for idx, row in df.iterrows():
            comment = clean_text(row.get("Comment"))
            if not comment:
                continue
            creator = COMMENT_CREATOR_MAP.get(as_str(row.get("Influencer")), as_str(row.get("Influencer")))
            rows.append(
                {
                    "dataset_type": "comment",
                    "country": "Kenya",
                    "comment_id": as_str(row.get("Comment ID")),
                    "influencer": creator,
                    "orientation": CONTENT_ORIENTATION.get(creator, "Unclear"),
                    "platform": as_str(row.get("Platform")),
                    "source_url": as_str(row.get("Source URL")),
                    "target_original_post": COMMENT_TARGETS.get(creator, "Original post/source content for this comment."),
                    "comment": comment,
                    "word_count": len(comment.split()),
                    "original_sheet": sheet,
                    "original_row": int(idx) + 2,
                }
            )
    return rows


def summarize_counts(rows: list[dict[str, object]], id_key: str) -> list[list[object]]:
    df = pd.DataFrame(rows)
    summary = [["Influencer", "Orientation", "Rows", "Platforms", "Mean words"]]
    for influencer, group in df.groupby("influencer", sort=True):
        platforms = ", ".join(sorted({str(x) for x in group["platform"].dropna().unique() if str(x)}))
        summary.append(
            [
                influencer,
                group["orientation"].mode().iloc[0] if len(group) else "",
                int(group[id_key].count()),
                platforms,
                round(float(group["word_count"].mean()), 1),
            ]
        )
    return summary


def load_validation_index() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if CONTENT_HUMAN_SOURCE.exists():
        df = pd.read_excel(CONTENT_HUMAN_SOURCE, sheet_name="Selected 200")
        for _, row in df.iterrows():
            rows.append(
                {
                    "dataset_type": "snippet",
                    "item_id": as_str(row.get("Content ID")),
                    "comment_id": "",
                    "influencer": as_str(row.get("Influencer")),
                    "orientation": as_str(row.get("Orientation")),
                    "platform": as_str(row.get("Platform")),
                    "coder": as_str(row.get("Coder")),
                    "source_file": CONTENT_HUMAN_SOURCE.name,
                    "overlap_design": "Top 200 balanced human-coding sample",
                    "text": clean_text(row.get("Text")),
                }
            )
    if AUDIENCE_HUMAN_SOURCE.exists():
        df = pd.read_excel(AUDIENCE_HUMAN_SOURCE, sheet_name="Selected 200")
        for _, row in df.iterrows():
            rows.append(
                {
                    "dataset_type": "comment",
                    "item_id": "",
                    "comment_id": as_str(row.get("Comment ID")),
                    "influencer": as_str(row.get("Influencer")),
                    "orientation": as_str(row.get("Orientation")),
                    "platform": as_str(row.get("Platform")),
                    "coder": as_str(row.get("Coder")),
                    "source_file": AUDIENCE_HUMAN_SOURCE.name,
                    "overlap_design": "Top 200 balanced human-coding sample",
                    "text": clean_text(row.get("Comment")),
                }
            )
    return rows


def validation_summary() -> list[list[object]]:
    files = [
        ("Snippet human sample", CONTENT_HUMAN_SOURCE, "Selected 200"),
        ("Audience human sample", AUDIENCE_HUMAN_SOURCE, "Selected 200"),
        ("Snippet overlap pool", CONTENT_OVERLAP_SOURCE, "Overlap Pool 20"),
        ("Audience overlap pool", AUDIENCE_OVERLAP_SOURCE, "Overlap Pool - 20"),
    ]
    out = [["Validation asset", "Rows", "Sheet", "File"]]
    for label, path, sheet in files:
        if path.exists():
            rows = len(pd.read_excel(path, sheet_name=sheet))
            out.append([label, rows, sheet, path.name])
        else:
            out.append([label, "Missing", sheet, path.name])
    return out


def main() -> None:
    snippets = load_snippets()
    comments = load_comments()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "sources": {
            "snippet_source": str(SNIPPET_SOURCE),
            "comment_source": str(COMMENT_SOURCE),
            "content_human_source": str(CONTENT_HUMAN_SOURCE),
            "audience_human_source": str(AUDIENCE_HUMAN_SOURCE),
            "content_overlap_source": str(CONTENT_OVERLAP_SOURCE),
            "audience_overlap_source": str(AUDIENCE_OVERLAP_SOURCE),
        },
        "overview": [
            ["Dataset", "Rows", "Distinct influencers", "Notes"],
            ["Creator snippets", len(snippets), len({r["influencer"] for r in snippets}), "Code influencer message only"],
            ["Audience comments", len(comments), len({r["influencer"] for r in comments}), "Code audience uptake/stance only"],
            ["Human validation index", len(load_validation_index()), "", "Existing balanced Top 200 content + Top 200 audience samples"],
        ],
        "snippet_counts": summarize_counts(snippets, "item_id"),
        "comment_counts": summarize_counts(comments, "comment_id"),
        "validation_summary": validation_summary(),
        "snippets": snippets,
        "comments": comments,
        "validation_index": load_validation_index(),
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT_JSON)


if __name__ == "__main__":
    main()
