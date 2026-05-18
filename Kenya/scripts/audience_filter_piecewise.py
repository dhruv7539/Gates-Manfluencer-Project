import argparse
import re
from pathlib import Path
from typing import List, Tuple

import pandas as pd


TEXT_COLUMN_CANDIDATES = [
    "text",
    "comment",
    "reply",
    "content",
    "body",
    "message",
]

LOW_CONTENT_PHRASES = {
    "ok", "okay", "yes", "no", "wow", "lol", "lmao", "true", "facts",
    "nice", "good", "great", "amen", "exactly", "period", "same",
    "thanks", "thank you", "interesting", "valid", "real", "yep", "nah"
}

STANCE_HINTS = {
    "agree", "disagree", "support", "challenge", "wrong", "right", "true",
    "false", "valid", "invalid", "accurate", "inaccurate", "facts", "nonsense"
}

EXPERIENCE_HINTS = {
    "i", "me", "my", "mine", "myself", "as a", "in my", "i've", "i’m", "ive"
}

LEARNING_HINTS = {
    "learn", "learned", "learnt", "realized", "realised", "didn't know",
    "never knew", "now i know", "opened my eyes", "understand better"
}

CHANGE_HINTS = {
    "changed my mind", "change my mind", "different view", "see things differently",
    "i used to think", "now i think", "made me rethink"
}

REINFORCEMENT_HINTS = {
    "exactly", "this is true", "i agree", "i always knew", "confirmed",
    "this proves", "that's what i've been saying", "been saying this"
}

ACTION_HINTS = {
    "should", "must", "need to", "stop", "start", "do better", "wake up",
    "speak up", "educate", "protect", "support", "leave", "avoid"
}

INFO_HINTS = {
    "because", "for example", "for instance", "according to", "in fact",
    "actually", "here is", "link", "source", "fact"
}

IDENTITY_HINTS = {
    "as a man", "as a woman", "as a father", "as a mother", "as a parent",
    "i'm a", "i am a", "from kenya", "from nigeria", "in kenya", "in nigeria"
}

GENDER_HINTS = {
    "man", "men", "male", "boy", "boys", "masculinity", "masculine",
    "woman", "women", "female", "girl", "girls", "femininity", "gender",
    "wife", "husband", "father", "mother", "feminist", "feminism"
}


def normalize_text(text: str) -> str:
    if pd.isna(text):
        return ""
    text = str(text).lower()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text).strip()
    return text


def safe_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def find_text_column(df: pd.DataFrame) -> str:
    lower_map = {c.lower(): c for c in df.columns}
    for candidate in TEXT_COLUMN_CANDIDATES:
        if candidate in lower_map:
            return lower_map[candidate]

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


def read_file(path: Path) -> pd.DataFrame:
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
    out = out.drop_duplicates(subset=["comment_text_norm"]).reset_index(drop=True)
    return out


def token_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def contains_url_only(text: str) -> bool:
    stripped = re.sub(r"https?://\S+|www\.\S+", "", text).strip()
    return stripped == "" and ("http://" in text or "https://" in text or "www." in text)


def contains_only_tags_mentions(text: str) -> bool:
    stripped = re.sub(r"[@#][\w_]+", "", text).strip()
    stripped = re.sub(r"[^\w\s]", "", stripped).strip()
    return stripped == "" and re.search(r"[@#][\w_]+", text) is not None


def contains_only_emojis_punct(text: str) -> bool:
    stripped = re.sub(r"[A-Za-z0-9]", "", text)
    stripped = re.sub(r"\s+", "", stripped)
    return stripped != "" and not re.search(r"[A-Za-z0-9]", stripped)


def is_low_content_short(text: str) -> bool:
    if token_count(text) > 4:
        return False
    return text.strip() in LOW_CONTENT_PHRASES


def has_any_phrase(text: str, phrases: set) -> bool:
    for phrase in phrases:
        if phrase in text:
            return True
    return False


def has_meaningful_structure(text: str) -> bool:
    words = token_count(text)
    if words >= 8:
        return True

    signals = 0
    for group in [
        STANCE_HINTS, EXPERIENCE_HINTS, LEARNING_HINTS, CHANGE_HINTS,
        REINFORCEMENT_HINTS, ACTION_HINTS, INFO_HINTS, IDENTITY_HINTS, GENDER_HINTS
    ]:
        if has_any_phrase(text, group):
            signals += 1

    if words >= 5 and signals >= 1:
        return True
    if words >= 3 and signals >= 2:
        return True

    if re.search(r"\b(is|are|was|were|be|been|being|do|does|did|have|has|had|should|must|need)\b", text):
        return True

    return False


def classify_comment(text: str, mode: str) -> Tuple[bool, str]:
    words = token_count(text)

    if text == "":
        return False, "empty"
    if contains_url_only(text):
        return False, "url_only"
    if contains_only_tags_mentions(text):
        return False, "mentions_tags_only"
    if contains_only_emojis_punct(text):
        return False, "emoji_or_punct_only"
    if is_low_content_short(text):
        return False, "low_content_short"

    if mode == "v1":
        if words < 3:
            return False, "too_few_words_v1"
        if has_meaningful_structure(text):
            return True, "substantive_v1"
        return False, "not_substantive_v1"

    if mode == "v2":
        if words < 5:
            return False, "too_few_words_v2"

        signals = sum([
            has_any_phrase(text, STANCE_HINTS),
            has_any_phrase(text, EXPERIENCE_HINTS),
            has_any_phrase(text, LEARNING_HINTS),
            has_any_phrase(text, CHANGE_HINTS),
            has_any_phrase(text, REINFORCEMENT_HINTS),
            has_any_phrase(text, ACTION_HINTS),
            has_any_phrase(text, INFO_HINTS),
            has_any_phrase(text, IDENTITY_HINTS),
            has_any_phrase(text, GENDER_HINTS),
        ])

        if words >= 8:
            return True, "substantive_v2_len"
        if signals >= 1 and has_meaningful_structure(text):
            return True, "substantive_v2_signal"

        return False, "not_substantive_v2"

    raise ValueError("mode must be v1 or v2")


def process_one_file(path: Path, mode: str) -> pd.DataFrame:
    df = read_file(path)

    records = []
    for _, row in df.iterrows():
        text = row["comment_text_norm"]
        keep, reason = classify_comment(text, mode)

        rec = row.to_dict()
        rec["mode"] = mode
        rec["word_count"] = token_count(text)
        rec["has_gender_hint"] = has_any_phrase(text, GENDER_HINTS)
        rec["has_stance_hint"] = has_any_phrase(text, STANCE_HINTS)
        rec["has_experience_hint"] = has_any_phrase(text, EXPERIENCE_HINTS)
        rec["has_learning_hint"] = has_any_phrase(text, LEARNING_HINTS)
        rec["has_change_hint"] = has_any_phrase(text, CHANGE_HINTS)
        rec["has_reinforcement_hint"] = has_any_phrase(text, REINFORCEMENT_HINTS)
        rec["has_action_hint"] = has_any_phrase(text, ACTION_HINTS)
        rec["has_info_hint"] = has_any_phrase(text, INFO_HINTS)
        rec["has_identity_hint"] = has_any_phrase(text, IDENTITY_HINTS)
        rec["keep"] = keep
        rec["keep_reason"] = reason
        records.append(rec)

    return pd.DataFrame(records)


def save_piece_outputs(results: pd.DataFrame, output_dir: Path, mode: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    all_path = output_dir / f"filtered_{mode}_all.csv"
    kept_path = output_dir / f"filtered_{mode}_kept.csv"
    summary_path = output_dir / f"filtered_{mode}_summary.csv"

    results.to_csv(all_path, index=False)
    results[results["keep"]].to_csv(kept_path, index=False)

    summary = pd.DataFrame([{
        "source_file": results["source_file"].iloc[0] if len(results) else "",
        "mode": mode,
        "total_comments": int(len(results)),
        "kept_comments": int(results["keep"].sum()),
        "retention_pct": round((results["keep"].sum() / len(results) * 100), 2) if len(results) else 0.0,
    }])
    summary.to_csv(summary_path, index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", required=True, type=str)
    parser.add_argument("--mode", required=True, choices=["v1", "v2"])
    parser.add_argument("--output-dir", required=True, type=str)
    args = parser.parse_args()

    input_file = Path(args.input_file)
    output_dir = Path(args.output_dir)

    results = process_one_file(input_file, args.mode)
    save_piece_outputs(results, output_dir, args.mode)

    kept = int(results["keep"].sum())
    total = int(len(results))
    pct = round((kept / total * 100), 2) if total else 0.0
    print(f"{input_file.name} | {args.mode} | kept {kept}/{total} | {pct}%")


if __name__ == "__main__":
    main()