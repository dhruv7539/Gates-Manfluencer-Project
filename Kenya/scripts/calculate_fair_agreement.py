#!/usr/bin/env python3
"""Calculate strict and conditional agreement on normalized codebook files."""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Iterable, Sequence


SINGLE_QIDS = {"Q1", "Q4", "Q5", "Q6", "Q14", "Q15", "Q16", "Q17", "Q18"}
MULTI_QIDS = {"Q1A", "Q2", "Q3", "Q7", "Q8", "Q9", "Q10", "Q11", "Q12", "Q13", "Q18A"}
CONDITIONAL_PARENTS = {"Q1A": "Q1", "Q18A": "Q18"}


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value).replace("\u00a0", " ")).strip()


def key(value: object) -> str:
    return clean(value).casefold()


def qid(header: str) -> str:
    match = re.match(r"\s*(Q\d+[a-z]?)\.", header, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


def read_file(path: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.reader(file))

    header_index = next(index for index, row in enumerate(rows[:10]) if "Content ID" in row)
    headers = rows[header_index]
    id_index = headers.index("Content ID")
    data: dict[str, dict[str, str]] = {}

    for row in rows[header_index + 1 :]:
        if not row or all(not clean(cell) for cell in row):
            continue
        padded = row + [""] * max(0, len(headers) - len(row))
        content_id = clean(padded[id_index])
        if content_id:
            data[content_id] = {
                header: clean(padded[index]) if index < len(padded) else ""
                for index, header in enumerate(headers)
            }

    return headers, data


def split_multi(value: str) -> set[str]:
    value = clean(value)
    if not value:
        return set()
    return {key(part) for part in re.split(r"\s*;\s*", value) if clean(part)}


def alpha_nominal(pairs: Iterable[tuple[str, str]]) -> tuple[float | None, int]:
    clean_pairs = [(a, b) for a, b in pairs if a and b]
    n_items = len(clean_pairs)
    if not clean_pairs:
        return None, 0

    observed_disagreement = sum(1 for a, b in clean_pairs if a != b) / n_items
    counts: Counter[str] = Counter()
    for a, b in clean_pairs:
        counts[a] += 1
        counts[b] += 1

    total = sum(counts.values())
    expected_agreement = sum(count * (count - 1) for count in counts.values()) / (total * (total - 1))
    expected_disagreement = 1 - expected_agreement
    if math.isclose(expected_disagreement, 0.0):
        return None, n_items

    return 1 - observed_disagreement / expected_disagreement, n_items


def score_single(
    ids: Sequence[str],
    header: str,
    human_rows: dict[str, dict[str, str]],
    llm_rows: dict[str, dict[str, str]],
) -> dict[str, object]:
    pairs = []
    exact = []
    for content_id in ids:
        h_value = key(human_rows[content_id].get(header, ""))
        l_value = key(llm_rows[content_id].get(header, ""))
        if not h_value or not l_value:
            continue
        pairs.append((h_value, l_value))
        exact.append(h_value == l_value)

    alpha, n_valid = alpha_nominal(pairs)
    agreement = mean([1.0 if item else 0.0 for item in exact]) if exact else None
    return {"n": n_valid, "exact": agreement, "alpha": alpha, "jaccard": None}


def score_multi(
    ids: Sequence[str],
    header: str,
    human_rows: dict[str, dict[str, str]],
    llm_rows: dict[str, dict[str, str]],
) -> dict[str, object]:
    exact_scores = []
    jaccards = []
    for content_id in ids:
        h_set = split_multi(human_rows[content_id].get(header, ""))
        l_set = split_multi(llm_rows[content_id].get(header, ""))
        union = h_set | l_set
        if not union:
            continue
        exact_scores.append(h_set == l_set)
        jaccards.append(len(h_set & l_set) / len(union))

    exact = mean([1.0 if item else 0.0 for item in exact_scores]) if exact_scores else None
    jaccard = mean(jaccards) if jaccards else None
    return {"n": len(jaccards), "exact": exact, "alpha": None, "jaccard": jaccard}


def fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def interpretation(score: float | None) -> str:
    if score is None:
        return "Not available"
    if score >= 0.80:
        return "Strong agreement"
    if score >= 0.67:
        return "Acceptable agreement"
    if score >= 0.50:
        return "Moderate / needs caution"
    return "Weak agreement"


def write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def calculate(human_path: Path, llm_path: Path, output_prefix: Path) -> None:
    human_headers, human_rows = read_file(human_path)
    llm_headers, llm_rows = read_file(llm_path)
    llm_by_qid = {qid(header): header for header in llm_headers}

    common_ids = sorted(set(human_rows) & set(llm_rows))
    strict_rows: list[dict[str, object]] = []
    fair_rows: list[dict[str, object]] = []

    for header in human_headers:
        question_id = qid(header)
        if question_id not in SINGLE_QIDS | MULTI_QIDS:
            continue
        if question_id not in llm_by_qid:
            continue

        llm_header = llm_by_qid[question_id]
        column_type = "Single-answer" if question_id in SINGLE_QIDS else "Multi-select"
        scorer = score_single if column_type == "Single-answer" else score_multi

        strict_score = scorer(common_ids, header, human_rows, llm_rows)
        strict_rows.append(row_for(header, question_id, column_type, "strict", strict_score))

        fair_ids = common_ids
        parent_qid = CONDITIONAL_PARENTS.get(question_id)
        if parent_qid:
            human_parent = next(h for h in human_headers if qid(h) == parent_qid)
            llm_parent = llm_by_qid[parent_qid]
            fair_ids = [
                content_id
                for content_id in common_ids
                if key(human_rows[content_id].get(human_parent, "")) == "yes"
                and key(llm_rows[content_id].get(llm_parent, "")) == "yes"
            ]

        fair_score = scorer(fair_ids, header, human_rows, llm_rows)
        fair_rows.append(row_for(header, question_id, column_type, "conditional", fair_score))

    write_outputs(output_prefix, strict_rows, fair_rows, len(common_ids))
    print(f"Wrote strict question scores to {output_prefix}_strict_question_scores.csv")
    print(f"Wrote fair question scores to {output_prefix}_fair_question_scores.csv")
    print(f"Wrote summary to {output_prefix}_summary.csv")


def row_for(
    header: str,
    question_id: str,
    column_type: str,
    method: str,
    score: dict[str, object],
) -> dict[str, object]:
    main_metric = "Krippendorff's alpha" if column_type == "Single-answer" else "Jaccard"
    main_score = score["alpha"] if column_type == "Single-answer" else score["jaccard"]
    return {
        "Question ID": question_id,
        "Codebook question": clean(header.split("Options:", 1)[0]),
        "Type": column_type,
        "Scoring method": method,
        "Agreement metric": main_metric,
        "Score": fmt(main_score),
        "Interpretation": interpretation(main_score if isinstance(main_score, float) else None),
        "Percent / exact agreement": fmt(score["exact"]),
        "Krippendorff's alpha": fmt(score["alpha"]),
        "Jaccard": fmt(score["jaccard"]),
        "Valid rows": score["n"],
    }


def summarize(rows: Sequence[dict[str, object]], label: str, overlapping_ids: int) -> list[dict[str, object]]:
    exact_scores = [float(row["Percent / exact agreement"]) for row in rows if row["Percent / exact agreement"]]
    alpha_scores = [float(row["Krippendorff's alpha"]) for row in rows if row["Krippendorff's alpha"]]
    jaccard_scores = [float(row["Jaccard"]) for row in rows if row["Jaccard"]]
    final_components = [
        float(row["Percent / exact agreement"])
        for row in rows
        if row["Type"] == "Single-answer" and row["Percent / exact agreement"]
    ] + jaccard_scores

    values = [
        ("Overall exact agreement", mean(exact_scores) if exact_scores else None),
        ("Average Krippendorff's alpha", mean(alpha_scores) if alpha_scores else None),
        ("Average Jaccard", mean(jaccard_scores) if jaccard_scores else None),
        ("Final combined agreement", mean(final_components) if final_components else None),
    ]
    return [
        {
            "Scoring method": label,
            "Score": name,
            "Value": fmt(value),
            "Interpretation": interpretation(value),
            "Overlapping Content IDs": overlapping_ids,
        }
        for name, value in values
    ]


def write_outputs(
    output_prefix: Path,
    strict_rows: Sequence[dict[str, object]],
    fair_rows: Sequence[dict[str, object]],
    overlapping_ids: int,
) -> None:
    fields = [
        "Question ID",
        "Codebook question",
        "Type",
        "Scoring method",
        "Agreement metric",
        "Score",
        "Interpretation",
        "Percent / exact agreement",
        "Krippendorff's alpha",
        "Jaccard",
        "Valid rows",
    ]
    write_csv(Path(f"{output_prefix}_strict_question_scores.csv"), fields, strict_rows)
    write_csv(Path(f"{output_prefix}_fair_question_scores.csv"), fields, fair_rows)
    summary_rows = summarize(strict_rows, "strict", overlapping_ids) + summarize(
        fair_rows, "fair conditional", overlapping_ids
    )
    write_csv(
        Path(f"{output_prefix}_summary.csv"),
        ["Scoring method", "Score", "Value", "Interpretation", "Overlapping Content IDs"],
        summary_rows,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate fair agreement on normalized files.")
    parser.add_argument("--human", required=True, type=Path)
    parser.add_argument("--llm", required=True, type=Path)
    parser.add_argument("--output-prefix", required=True, type=Path)
    args = parser.parse_args()
    calculate(args.human, args.llm, args.output_prefix)


if __name__ == "__main__":
    main()
