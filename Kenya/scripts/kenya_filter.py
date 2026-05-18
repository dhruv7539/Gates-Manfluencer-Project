import argparse
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd


# =========================
# PATHS
# =========================

HERE = Path(__file__).resolve().parent
FILTERING_ROOT = HERE.parent
KEYWORDS_DIR = FILTERING_ROOT / "keywords"
INPUTS_DIR = FILTERING_ROOT / "inputs" / "Kenya"
OUTPUTS_DIR = FILTERING_ROOT / "outputs" / "Kenya"

# =========================
# CONFIG
# =========================

DEFAULT_KEYWORD_FILE = str(KEYWORDS_DIR / "NLC Proposed keywords.xlsx")

KENYA_FILES = [
    "Full Tweet Stay away from vulgar women.xlsx",
    "Tweet_A woman can't love a man. It is a man who loves a woman..xlsx",
    "Tweet; I wonder how some men are satisfied with just one woman... .xlsx",
    "Tweet- There is no amount of .xlsx",
    "Instagram;A Happy Women's Day! Documentary announcement .xlsx",
    "Youtube- Episode 1- A Girl Dad on a Mission .xlsx",
    "Youtube- Undoing my Father's damage.xlsx",
    "Youtube-My voice was beaten out of me by my father - Toxic masculinity .xlsx",
    "Tiktok; Young man who thinks it's a shame not having a car at 35.xlsx",
    "Tiktok; Men Are Not Missing. They Are Evolving!.csv.xlsx",
]

TEXT_COLUMN_CANDIDATES = [
    "text",
    "comment",
    "reply",
    "content",
    "body",
    "message",
]

# generic context terms used in both V1 and V2
CONTEXT_TERMS = {
    "man", "men", "male", "males",
    "boy", "boys", "boychild", "boy child",
    "masculinity", "masculine",
    "gender", "gender roles", "gender role", "gender norms", "gender norm",
    "woman", "women", "female", "females",
    "wife", "wives", "husband", "husbands",
    "father", "fathers", "dad", "dads",
    "mother", "mothers",
    "feminism", "feminist", "feminists",
}

# in V2, these are treated as context only, not as standalone evidence
GENERIC_TERMS_V2 = {
    "man", "men", "male", "males",
    "boy", "boys", "boychild", "boy child",
    "masculinity", "masculine",
    "gender", "gender roles", "gender role", "gender norms", "gender norm",
    "woman", "women", "female", "females",
    "wife", "wives", "husband", "husbands",
    "father", "fathers", "dad", "dads",
    "mother", "mothers",
    "respect", "provide", "provider", "lead", "leader", "leaders",
    "strength", "strong", "traditional", "tradition", "modern",
    "relationship", "relationships", "marriage", "married",
    "family", "children", "child", "love",
}


# =========================
# HELPERS
# =========================

def normalize_text(text: str) -> str:
    if pd.isna(text):
        return ""
    text = str(text).lower()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text).strip()
    return text


def find_text_column(df: pd.DataFrame) -> str:
    lower_map = {c.lower(): c for c in df.columns}
    for candidate in TEXT_COLUMN_CANDIDATES:
        if candidate in lower_map:
            return lower_map[candidate]

    # fallback: choose the object column with the longest average text
    object_cols = [c for c in df.columns if df[c].dtype == "object"]
    if not object_cols:
        raise ValueError("No usable text column found.")

    best_col = None
    best_score = -1
    for c in object_cols:
        lengths = df[c].astype(str).map(len)
        score = lengths.mean()
        if score > best_score:
            best_score = score
            best_col = c

    return best_col


def compile_pattern(term: str) -> re.Pattern:
    """
    Word-boundary-ish matcher for phrases.
    Handles spaces flexibly.
    """
    term = normalize_text(term)
    escaped = re.escape(term)
    escaped = escaped.replace(r"\ ", r"\s+")
    pattern = rf"(?<!\w){escaped}(?!\w)"
    return re.compile(pattern, flags=re.IGNORECASE)


def extract_relevance_columns(df: pd.DataFrame) -> Tuple[str, str]:
    """
    Try to locate Kenya keyword and relevance columns.
    """
    cols = list(df.columns)
    lower_cols = {c.lower(): c for c in cols}

    keyword_col = None
    relevance_col = None

    # likely keyword columns
    keyword_candidates = [
        "keyword", "keywords", "term", "terms", "phrase", "phrases"
    ]
    for cand in keyword_candidates:
        if cand in lower_cols:
            keyword_col = lower_cols[cand]
            break

    # likely relevance columns
    for c in cols:
        cl = c.lower()
        if "relevance" in cl and ("kenya" in cl or "masculinity" in cl):
            relevance_col = c
            break

    if keyword_col is None:
        # fallback to first object column
        object_cols = [c for c in cols if df[c].dtype == "object"]
        if not object_cols:
            raise ValueError("Could not find keyword column in keyword sheet.")
        keyword_col = object_cols[0]

    if relevance_col is None:
        # fallback to any relevance column
        for c in cols:
            if "relevance" in c.lower():
                relevance_col = c
                break

    if relevance_col is None:
        raise ValueError("Could not find Kenya relevance column in keyword sheet.")

    return keyword_col, relevance_col


def load_kenya_keywords(keyword_file: Path) -> Tuple[Set[str], Set[str]]:
    xl = pd.ExcelFile(keyword_file)
    kenya_sheet = None

    for s in xl.sheet_names:
        if "kenya" in s.lower():
            kenya_sheet = s
            break

    if kenya_sheet is None:
        raise ValueError("Could not find a Kenya sheet in the keyword workbook.")

    df = pd.read_excel(keyword_file, sheet_name=kenya_sheet)
    keyword_col, relevance_col = extract_relevance_columns(df)

    df = df[[keyword_col, relevance_col]].copy()
    df[keyword_col] = df[keyword_col].map(normalize_text)
    df[relevance_col] = df[relevance_col].astype(str).str.lower().str.strip()

    high_terms = set(
        df.loc[
            df[relevance_col].str.contains("high", na=False) &
            df[keyword_col].ne(""),
            keyword_col
        ].tolist()
    )

    moderate_terms = set(
        df.loc[
            df[relevance_col].str.contains("moder", na=False) &
            df[keyword_col].ne(""),
            keyword_col
        ].tolist()
    )

    # remove blanks and very short junk
    high_terms = {t for t in high_terms if len(t) >= 2}
    moderate_terms = {t for t in moderate_terms if len(t) >= 2}

    return high_terms, moderate_terms


def match_terms(text: str, term_patterns: Dict[str, re.Pattern]) -> List[str]:
    hits = []
    for term, pat in term_patterns.items():
        if pat.search(text):
            hits.append(term)
    return hits


def read_comment_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported file type: {path}")

    text_col = find_text_column(df)

    out = df.copy()
    out["source_file"] = path.name
    out["source_text_col"] = text_col
    out["comment_text"] = out[text_col].astype(str)
    out["comment_text_norm"] = out["comment_text"].map(normalize_text)

    return out


def apply_filter_rule(
    df: pd.DataFrame,
    high_terms: Set[str],
    moderate_terms: Set[str],
    mode: str,
) -> pd.DataFrame:
    if mode not in {"v1", "v2"}:
        raise ValueError("mode must be 'v1' or 'v2'")

    if mode == "v2":
        high_terms = {t for t in high_terms if t not in GENERIC_TERMS_V2}
        moderate_terms = {t for t in moderate_terms if t not in GENERIC_TERMS_V2}

    high_patterns = {t: compile_pattern(t) for t in high_terms}
    moderate_patterns = {t: compile_pattern(t) for t in moderate_terms}
    context_patterns = {t: compile_pattern(t) for t in CONTEXT_TERMS}

    records = []
    for _, row in df.iterrows():
        text = row["comment_text_norm"]

        high_hits = match_terms(text, high_patterns)
        moderate_hits = match_terms(text, moderate_patterns)
        context_hits = match_terms(text, context_patterns)

        keep = (
            (len(high_hits) >= 1) or
            (len(moderate_hits) >= 2) or
            (len(moderate_hits) >= 1 and len(context_hits) >= 1)
        )

        reason = None
        if len(high_hits) >= 1:
            reason = ">=1_high"
        elif len(moderate_hits) >= 2:
            reason = ">=2_moderate"
        elif len(moderate_hits) >= 1 and len(context_hits) >= 1:
            reason = ">=1_moderate_plus_context"
        else:
            reason = "reject"

        rec = row.to_dict()
        rec["mode"] = mode
        rec["high_hits"] = "; ".join(sorted(high_hits))
        rec["moderate_hits"] = "; ".join(sorted(moderate_hits))
        rec["context_hits"] = "; ".join(sorted(context_hits))
        rec["high_hit_count"] = len(high_hits)
        rec["moderate_hit_count"] = len(moderate_hits)
        rec["context_hit_count"] = len(context_hits)
        rec["keep"] = keep
        rec["keep_reason"] = reason
        records.append(rec)

    return pd.DataFrame(records)


def build_master_corpus(input_dir: Path, files: List[str]) -> pd.DataFrame:
    parts = []
    missing = []

    for fname in files:
        path = input_dir / fname
        if not path.exists():
            missing.append(fname)
            continue
        parts.append(read_comment_file(path))

    if missing:
        print("Warning: these files were not found and were skipped:")
        for m in missing:
            print(f"  - {m}")

    if not parts:
        raise ValueError("No Kenya files were found.")

    df = pd.concat(parts, ignore_index=True)

    # remove empty/near-empty comments
    df = df[df["comment_text_norm"].str.len() > 0].copy()

    # dedupe by normalized text + source file
    df = df.drop_duplicates(subset=["source_file", "comment_text_norm"]).reset_index(drop=True)

    return df


def save_outputs(
    output_dir: Path,
    master_df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    mode: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    master_path = output_dir / "kenya_master_corpus.csv"
    kept_path = output_dir / f"kenya_filtered_{mode}_kept.csv"
    full_path = output_dir / f"kenya_filtered_{mode}_all.csv"
    summary_path = output_dir / f"kenya_filtered_{mode}_summary.csv"

    master_df.to_csv(master_path, index=False)
    filtered_df.to_csv(full_path, index=False)
    filtered_df[filtered_df["keep"]].to_csv(kept_path, index=False)

    summary = (
        filtered_df
        .groupby("source_file", dropna=False)
        .agg(
            total_comments=("comment_text", "count"),
            kept_comments=("keep", "sum"),
        )
        .reset_index()
    )
    summary["retention_pct"] = (summary["kept_comments"] / summary["total_comments"] * 100).round(2)
    summary.to_csv(summary_path, index=False)

    print("\nSaved:")
    print(f"  {master_path}")
    print(f"  {full_path}")
    print(f"  {kept_path}")
    print(f"  {summary_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=str, default=str(INPUTS_DIR))
    parser.add_argument("--keyword-file", type=str, default=DEFAULT_KEYWORD_FILE)
    parser.add_argument("--mode", type=str, choices=["v1", "v2"], required=True)
    parser.add_argument("--output-dir", type=str, default=str(OUTPUTS_DIR / "filter_output"))
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    keyword_file = Path(args.keyword_file)
    output_dir = Path(args.output_dir)

    high_terms, moderate_terms = load_kenya_keywords(keyword_file)
    print(f"Loaded Kenya keywords: {len(high_terms)} high, {len(moderate_terms)} moderate")

    master_df = build_master_corpus(input_dir, KENYA_FILES)
    print(f"Built Kenya corpus: {len(master_df)} unique comments")

    filtered_df = apply_filter_rule(master_df, high_terms, moderate_terms, args.mode)

    kept = filtered_df["keep"].sum()
    total = len(filtered_df)
    print(f"Mode {args.mode}: kept {kept}/{total} comments ({kept/total*100:.2f}%)")

    save_outputs(output_dir, master_df, filtered_df, args.mode)


if __name__ == "__main__":
    main()