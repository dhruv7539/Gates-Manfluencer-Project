#!/usr/bin/env python3
"""
Normalize Kenya codebook files before human/LLM agreement scoring.

This script does not recode substantive answers. It standardizes formatting:
  - trims and collapses whitespace
  - maps obvious label variants to codebook labels
  - uses semicolon separators for multi-select fields
  - sorts multi-select answers in codebook option order
  - treats Q3, Q12, and Q13 as multi-select for agreement scoring
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Sequence


IDENTITY_COLUMNS = {
    "content id",
    "context",
    "content text / description",
}

FORCE_MULTI_QIDS = {"Q3", "Q12", "Q13"}


def clean_space(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\u00a0", " ")).strip()


def simple_key(value: object) -> str:
    text = clean_space(value).casefold()
    text = text.replace("’", "'")
    text = text.replace("&", " and ")
    text = re.sub(r"\be\.g\.\b", "eg", text)
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def qid(header: str) -> str:
    match = re.match(r"\s*(Q\d+[a-z]?)\.", header, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def is_open_text(header: str) -> bool:
    key = clean_space(header).casefold()
    return "open text" in key or "if other, specify" in key


def is_multi_select(header: str) -> bool:
    key = clean_space(header).casefold()
    return (
        "choose all that apply" in key
        or "select all that apply" in key
        or qid(header) in FORCE_MULTI_QIDS
    )


def parse_options(header: str) -> list[str]:
    if "Options:" not in header:
        return []

    option_text = header.split("Options:", 1)[1]
    option_text = re.sub(r"\bOpen text\b", "", option_text, flags=re.IGNORECASE)
    parts = re.split(r"\n| / ", option_text)
    options: list[str] = []
    seen: set[str] = set()

    for part in parts:
        label = clean_space(part).strip(" /")
        if not label:
            continue
        key = simple_key(label)
        if key not in seen:
            seen.add(key)
            options.append(label)
    return options


def option_aliases(question_id: str, option: str) -> set[str]:
    aliases = {simple_key(option)}
    option_key = simple_key(option)

    manual: dict[tuple[str, str], Iterable[str]] = {
        ("Q2", "Dating/marriage"): ["Dating / Marriage", "Dating marriage", "Dating / Sex", "Dating"],
        ("Q2", "Family/children"): ["Family"],
        ("Q2", "Fitness/self-improvement"): ["Fitness / self improvement", "Fitness self improvement"],
        ("Q2", "Mental health"): ["Mental heath"],
        ("Q2", "Gender issues, e.g. equality"): ["Gender issues", "Gender issue", "Gender equality"],
        ("Q2", "Social issues, e.g. corruption"): ["Social issues", "Social issue", "Corruption"],
        ("Q3", "Interview/conversational content"): [
            "Interview conversational content",
            "Conversational content",
        ],
        ("Q3", "Motivational/self-help content"): [
            "Self-help Content",
            "Self help content",
        ],
        ("Q3", "Commentary/reaction content"): [
            "Commentary Content",
            "Commentary content",
            "Commentary",
            "Reaction content",
        ],
        ("Q10", "Commentary/opinion"): [
            "Commentary Content",
            "Commentary",
        ],
        ("Q5", "More regressive/traditional/restrictive"): [
            "More regressive",
            "More Regressive",
        ],
        ("Q5", "More progressive/equitable/expansive"): [
            "More progressive",
            "More Progressive",
        ],
        ("Q5", "Does not address masculinity or gender norms"): [
            "Does not address masculinity/gender norms",
        ],
        ("Q7", "Men need to dominate/lead"): ["Men need to dominate/ead"],
        ("Q7", "Men need to be emotionally open"): [
            "Men need to be more emotionally open",
            "Men need to be more emotionally open and heal",
        ],
        ("Q7", "Men need to not show emotions"): ["Men need to now show emotions"],
        ("Q7", "Mixed/unclear"): ["Mixed"],
        ("Q8", "Kenyan or Nigerian political/social problems"): [
            "Kenyan cultural problems",
            "Kenyan Social & Cultural Problems",
            "Kenyan political social problems",
            "Nigerian political social problems",
        ],
        ("Q8", "Women/feminism"): [
            "Women / Women's Behavior",
            "Women's behavior",
            "Women behavior",
            "Women",
        ],
        ("Q8", "Men’s behavior"): ["Men's behavior", "Men behavior"],
        ("Q8", "Mental health/emotional struggle"): [
            "Mental Health",
            "Mental health",
            "Emotional struggle",
        ],
        ("Q12", "Generalizations about men/women"): [
            "Generalizations about women",
            "Generalizations about men",
        ],
        ("Q12", "Cultural/social observations"): [
            "Cultural / Social Observations",
            "Cultural social observations",
        ],
        ("Q12", "Moral/religious claims"): [
            "moral/religious claims",
            "Moral religious claims",
        ],
        ("Q13", "No justification"): ["No Justification"],
        ("Q13", "Anecdotal examples"): ["Anecdotal Examples"],
        ("Q13", "Presented as common sense"): ["Common sense"],
        ("Q13", "References external sources, such as other influencers"): [
            "References external sources such as other influencers",
            "References external sources",
        ],
        ("Q1A", "Use of all CAPS"): ["Uses all CAPS"],
        ("Q11", "Self expression/identity construction"): ["Identity Construction"],
        ("Q18", "No"): ["NO"],
    }

    for alias in manual.get((question_id, option), []):
        aliases.add(simple_key(alias))

    # Common safe variants.
    if "/" in option:
        aliases.add(simple_key(option.replace("/", " / ")))
        aliases.add(simple_key(option.replace("/", " ")))
    if "’" in option:
        aliases.add(simple_key(option.replace("’", "'")))

    # Avoid making "Other" a broad substring match. It can appear inside
    # labels such as "other influencers".
    if option_key == "other":
        return {"other"}
    return aliases


def contains_alias(value_key: str, alias: str) -> bool:
    if not alias:
        return False
    return re.search(rf"(^|\s){re.escape(alias)}($|\s)", value_key) is not None


def match_options(value: str, question_id: str, options: Sequence[str]) -> list[str]:
    value = clean_space(value)
    if not value:
        return []

    value_key = simple_key(value)
    matched: list[tuple[int, int, str]] = []

    for index, option in enumerate(options):
        option_key = simple_key(option)
        aliases = option_aliases(question_id, option)
        for alias in aliases:
            if option_key == "other":
                parts = [simple_key(part) for part in re.split(r"\s*(?:;|,|\||\n|\r|\t)\s*", value)]
                if "other" not in parts:
                    continue
                position = parts.index("other")
            elif contains_alias(value_key, alias):
                position = value_key.find(alias)
            else:
                continue
            matched.append((index, position, option))
            break

    if matched:
        seen: set[str] = set()
        ordered: list[str] = []
        for _, _, option in sorted(matched):
            key = simple_key(option)
            if key not in seen:
                seen.add(key)
                ordered.append(option)
        return ordered

    return []


def split_fallback(value: str) -> list[str]:
    return [
        clean_space(part)
        for part in re.split(r"\s*(?:;|,|\||\n|\r|\t)\s*", value)
        if clean_space(part)
    ]


def normalize_cell(value: str, header: str) -> tuple[str, bool]:
    value = clean_space(value)
    if not value:
        return "", False

    header_key = clean_space(header).casefold()
    if clean_space(header).casefold() in IDENTITY_COLUMNS or is_open_text(header):
        return value, False

    question_id = qid(header)
    options = parse_options(header)
    if not options:
        return value, False

    matched = match_options(value, question_id, options)
    if is_multi_select(header):
        if matched:
            return "; ".join(matched), True
        return "; ".join(split_fallback(value)), False

    if matched:
        return matched[0], True
    return value, False


def read_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        return [row for row in csv.reader(file)]


def normalize_file(path: Path, output_path: Path) -> dict[str, object]:
    rows = read_csv(path)
    if not rows:
        raise ValueError(f"{path} is empty")

    header_index = next(
        (index for index, row in enumerate(rows[:10]) if "Content ID" in row),
        None,
    )
    if header_index is None:
        raise ValueError(f"Could not find Content ID header in {path}")

    headers = rows[header_index]
    output_rows = [list(row) for row in rows[: header_index + 1]]
    changed_cells: Counter[str] = Counter()
    unresolved: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows[header_index + 1 :]:
        if not row or all(not clean_space(cell) for cell in row):
            continue
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        cleaned_row: list[str] = []
        for index, header in enumerate(headers):
            original = padded[index] if index < len(padded) else ""
            cleaned, matched = normalize_cell(original, header)
            cleaned_row.append(cleaned)
            if clean_space(original) != cleaned:
                changed_cells[qid(header) or header or f"column_{index + 1}"] += 1
            if (
                clean_space(original)
                and parse_options(header)
                and not matched
                and clean_space(header).casefold() not in IDENTITY_COLUMNS
                and not is_open_text(header)
            ):
                unresolved[qid(header) or header][clean_space(original)] += 1
        output_rows.append(cleaned_row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerows(output_rows)

    return {
        "input": str(path),
        "output": str(output_path),
        "rows": len(output_rows) - header_index - 1,
        "columns": len(headers),
        "changed_cells": changed_cells,
        "unresolved": unresolved,
    }


def write_report(path: Path, reports: Sequence[dict[str, object]]) -> None:
    lines: list[str] = []
    for report in reports:
        lines.append(f"Input: {report['input']}")
        lines.append(f"Output: {report['output']}")
        lines.append(f"Rows: {report['rows']}")
        lines.append(f"Columns: {report['columns']}")
        lines.append("Changed cells by question:")
        changed_cells: Counter[str] = report["changed_cells"]  # type: ignore[assignment]
        if changed_cells:
            for question, count in sorted(changed_cells.items()):
                lines.append(f"  {question}: {count}")
        else:
            lines.append("  None")
        lines.append("Unresolved non-canonical values:")
        unresolved: dict[str, Counter[str]] = report["unresolved"]  # type: ignore[assignment]
        if unresolved:
            for question, counter in sorted(unresolved.items()):
                lines.append(f"  {question}:")
                for value, count in counter.most_common(20):
                    lines.append(f"    {count}x {value}")
        else:
            lines.append("  None")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize codebook CSV files for agreement scoring.")
    parser.add_argument("--human", required=True, type=Path)
    parser.add_argument("--llm", required=True, type=Path)
    parser.add_argument("--human-output", required=True, type=Path)
    parser.add_argument("--llm-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    reports = [
        normalize_file(args.human, args.human_output),
        normalize_file(args.llm, args.llm_output),
    ]
    write_report(args.report, reports)

    print(f"Wrote normalized human file to {args.human_output}")
    print(f"Wrote normalized LLM file to {args.llm_output}")
    print(f"Wrote normalization report to {args.report}")


if __name__ == "__main__":
    main()
