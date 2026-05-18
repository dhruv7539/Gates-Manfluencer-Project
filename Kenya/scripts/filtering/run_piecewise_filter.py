"""
Piecewise Kenya filter runner.
Processes each Kenya audience file independently through V1 and V2 filtering,
producing separate output folders per file.
"""
import re
import sys
import traceback
from pathlib import Path

import pandas as pd

from kenya_filter import (
    KENYA_FILES,
    DEFAULT_KEYWORD_FILE,
    INPUTS_DIR,
    OUTPUTS_DIR,
    load_kenya_keywords,
    read_comment_file,
    apply_filter_rule,
)


OUTPUT_ROOT = OUTPUTS_DIR / "piecewise_filter_output"


def safe_folder_name(filename: str) -> str:
    name = Path(filename).stem
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def process_single_file(
    file_path: Path,
    high_terms: set,
    moderate_terms: set,
) -> dict:
    piece_name = safe_folder_name(file_path.name)
    piece_dir = OUTPUT_ROOT / piece_name

    result = {
        "source_file": file_path.name,
        "piece_name": piece_name,
    }

    df = read_comment_file(file_path)
    df = df[df["comment_text_norm"].str.len() > 0].copy()
    df = df.drop_duplicates(subset=["source_file", "comment_text_norm"]).reset_index(drop=True)
    total = len(df)
    result["total"] = total

    for mode in ("v1", "v2"):
        mode_dir = piece_dir / mode
        mode_dir.mkdir(parents=True, exist_ok=True)

        filtered = apply_filter_rule(df, high_terms, moderate_terms, mode)
        kept_count = int(filtered["keep"].sum())

        filtered.to_csv(mode_dir / f"filtered_{mode}_all.csv", index=False)
        filtered[filtered["keep"]].to_csv(mode_dir / f"filtered_{mode}_kept.csv", index=False)

        summary = pd.DataFrame([{
            "source_file": file_path.name,
            "total_comments": total,
            "kept_comments": kept_count,
            "retention_pct": round(kept_count / total * 100, 2) if total else 0.0,
        }])
        summary.to_csv(mode_dir / f"filtered_{mode}_summary.csv", index=False)

        result[f"{mode}_kept"] = kept_count
        result[f"{mode}_pct"] = round(kept_count / total * 100, 2) if total else 0.0

    return result


def main():
    input_dir = INPUTS_DIR
    keyword_file = Path(DEFAULT_KEYWORD_FILE)

    print("Loading keywords...")
    high_terms, moderate_terms = load_kenya_keywords(keyword_file)
    print(f"  {len(high_terms)} high, {len(moderate_terms)} moderate terms loaded.\n")

    results = []
    failures = []

    for fname in KENYA_FILES:
        file_path = input_dir / fname
        if not file_path.exists():
            print(f"[SKIP] Not found: {fname}")
            failures.append({"file": fname, "error": "File not found"})
            continue

        print(f"Processing: {fname}")
        try:
            res = process_single_file(file_path, high_terms, moderate_terms)
            results.append(res)
            print(f"  -> {res['piece_name']}/  v1: {res['v1_kept']}/{res['total']}  v2: {res['v2_kept']}/{res['total']}")
        except Exception as e:
            print(f"  [FAIL] {e}")
            traceback.print_exc()
            failures.append({"file": fname, "error": str(e)})

    # Final report
    print("\n" + "=" * 100)
    print("FINAL REPORT")
    print("=" * 100)

    if results:
        header = f"{'Source File':<75} {'V1 Kept':>8} {'V1 %':>8} {'V2 Kept':>8} {'V2 %':>8}"
        print(header)
        print("-" * 100)
        for r in results:
            print(
                f"{r['source_file']:<75} "
                f"{r['v1_kept']:>8} "
                f"{r['v1_pct']:>7.2f}% "
                f"{r['v2_kept']:>8} "
                f"{r['v2_pct']:>7.2f}%"
            )
        print("-" * 100)

    if failures:
        print(f"\n{len(failures)} file(s) failed:")
        for f in failures:
            print(f"  - {f['file']}: {f['error']}")

    print(f"\nOutputs saved to: {OUTPUT_ROOT.resolve()}")


if __name__ == "__main__":
    main()
