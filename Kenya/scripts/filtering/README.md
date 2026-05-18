# Kenya audience comment filtering

Kenya-only scripts for the Gates Manfluencer project. Applies keyword- and
linguistic-signal-based filters to raw audience engagement workbooks and
produces per-piece kept workbooks for downstream coding.

(Nigeria filtering lives under `Nigeria/scripts/` in this repo.)

## Layout

```
Filtering/
├── README.md                         (this file)
│
├── scripts/                          All Python code
│   ├── kenya_filter.py               Kenya corpus-level filter (v1/v2)
│   ├── run_piecewise_filter.py       Per-piece Kenya runner (v1/v2)
│   ├── audience_filter_piecewise.py  Single-file filter (platform-agnostic)
│   ├── filter_kenya_comments.py      Keyword-match filter (conservative / expanded)
│   └── create_kenya_top4_relevant_workbook.py
│                                     Builds top-4 most-relevant workbook
│
├── keywords/
│   ├── NLC Proposed keywords.xlsx    Master keyword workbook (Kenya + Nigeria sheets)
│   └── conservative_excluded_keywords.txt  Nigeria conservative-mode exclusion list
│
├── inputs/
│   ├── Kenya/                        10 Kenya audience-piece XLSXs
│   │                                 + Kenya audience piece.zip (source bundle)
│   └── Nigeria/                      10 Nigeria audience-piece XLSXs
│
├── outputs/
│   ├── Kenya/
│   │   ├── filtered_output/                  Conservative keyword filter
│   │   ├── filtered_output_expanded_variants/ Expanded-variant keyword filter
│   │   ├── piecewise_filter_output/           Per-piece v1/v2 piecewise runs
│   │   └── Kenya_top4_most_relevant_comments.xlsx
│   │
│   └── Nigeria/
│       ├── filtered_output/                   Standard keyword filter
│       ├── filtered_output_conservative/      Conservative keyword filter
│       ├── filtered_output_conservative_strict/
│       │                                      Strict conservative filter
│       │                                      (uses exclusion list)
│       └── Nigeria_doc_downloads/             Source download manifest + report
│
└── reports/
    └── kenya_top4_scope_audit.md              Scope audit for the top-4 Kenya workbook
```

## Running the filters

All scripts resolve their paths relative to this folder (via `__file__`),
so you can run them from anywhere without `cd`-ing first.

### Per-piece Kenya piecewise filter (v1 + v2)

```bash
python scripts/run_piecewise_filter.py
```

Reads every XLSX under `inputs/Kenya/` listed in `kenya_filter.KENYA_FILES`,
runs both v1 and v2 modes, and writes per-piece `v1/` and `v2/` folders
under `outputs/Kenya/piecewise_filter_output/`.

### Corpus-level Kenya filter

```bash
python scripts/kenya_filter.py --mode v2
# or override paths:
python scripts/kenya_filter.py \
  --mode v2 \
  --input-dir  ./inputs/Kenya \
  --keyword-file "./keywords/NLC Proposed keywords.xlsx" \
  --output-dir ./outputs/Kenya/filter_output_v2
```

### Keyword-match filter (Kenya, conservative or expanded)

```bash
python scripts/filter_kenya_comments.py --match-mode conservative
python scripts/filter_kenya_comments.py --match-mode expanded
```

Outputs go to `outputs/Kenya/filtered_output/` or
`outputs/Kenya/filtered_output_expanded_variants/` respectively.

### Single-file piecewise filter (any platform)

```bash
python scripts/audience_filter_piecewise.py \
  --input-file ./inputs/Kenya/"Full Tweet Stay away from vulgar women.xlsx" \
  --mode v2 \
  --output-dir ./outputs/Kenya/ad_hoc/vulgar_women
```

### Top-4 most-relevant workbook (Kenya)

```bash
python scripts/create_kenya_top4_relevant_workbook.py
```

Reads the four priority pieces from `outputs/Kenya/filtered_output/` and
writes `outputs/Kenya/Kenya_top4_most_relevant_comments.xlsx`.

## Filter modes, at a glance

| Mode | Used by | Criteria |
|---|---|---|
| `v1` (piecewise) | `run_piecewise_filter`, `audience_filter_piecewise` | Word-count floor + basic linguistic-signal hints. More permissive. |
| `v2` (piecewise) | same | Stricter. ≥ 5 words + (≥ 8 words OR at least one hint group + meaningful structure). |
| `conservative` (keyword) | `filter_kenya_comments` | Case-insensitive exact-phrase matches against the Kenya/Nigeria sheets of the keyword workbook. |
| `expanded` (keyword) | `filter_kenya_comments` | Conservative matches + morphological variants (lowercased stems, common plural/verb forms). |
| `conservative_strict` (Nigeria) | `filter_kenya_comments` + exclusion list | Conservative keyword matches minus any rows matching `keywords/conservative_excluded_keywords.txt`. |

## Dependencies

```bash
pip install pandas openpyxl
```

All scripts write their outputs to subdirectories under `outputs/` and
never mutate `inputs/`, so re-runs are safe.
