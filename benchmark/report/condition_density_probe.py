"""P1 condition-density probe for the prenatal corpus.

Three phases:

* ``prescan``  – regex pass over the 26 indexed articles: gestational-age
  mentions, condition vocabulary, supersession language; per-article density.
* ``sample``   – pick pages for LLM extraction: the two GA-densest pages per
  article (mining set) plus one seeded-random page per article (unbiased
  density set).  Writes page texts for the extraction step.
* ``analyze``  – consume the LLM extraction JSON, extrapolate corpus-wide
  statement counts and mine condition-variant groups.

Standard library only.  Usage:
    python benchmark/report/condition_density_probe.py prescan
    python benchmark/report/condition_density_probe.py sample --out sampling.json
    python benchmark/report/condition_density_probe.py analyze \
        --statements density_statements_raw.json --out analysis.json
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "benchmark" / "data" / "corpus"
INPUT_DIR = CORPUS_DIR / "input"
RESULTS_DIR = REPO_ROOT / "benchmark" / "results" / "corpus-audit-20260912"
SEED = 20260912

PAGE_MARK_RE = re.compile(r"(?m)^## Page (\d+)\s*$")
WATERMARK_RE = re.compile(
    r"Downloaded from|See the Terms and Conditions|OA articles are governed"
)

GA_PLUS_RE = re.compile(r"\b\d{1,2}\s*\+\s*\d\b")
GA_WEEKS_RE = re.compile(r"\b\d{1,2}(?:\.\d)?\s+weeks\b")
GA_WINDOW_RE = re.compile(
    r"\b\d{1,2}\s*(?:to|–|—|−|-)\s*\d{1,2}\s+weeks\b"
)
GESTATION_PHRASE_RE = re.compile(
    r"weeks\s*['’]?\s*(?:of\s+)?gestation\b|gestational age|weeks\s+of\s+amenorrh?oea",
    re.IGNORECASE,
)
POPULATION_RE = re.compile(
    r"\b(?:twin|triplet|monochorionic|dichorionic|singleton|high[- ]risk|"
    r"low[- ]risk|unselected|obese|IVF)\b",
    re.IGNORECASE,
)
PARAMETER_RE = re.compile(
    r"\b(?:CRL|NT|BPD|HC|AC|FL|EFW|MCA\s?PI|UA\s?PI|DV|crown[- ]rump)\b"
)
PLANE_RE = re.compile(
    r"\b(?:four[- ]chamber|3VV|three[- ]vessel|transverse cerebellar|"
    r"transabdominal|transvaginal|midsagittal|axial plane|sagittal)\b",
    re.IGNORECASE,
)
SUPERSESSION_RE = re.compile(
    r"\b(?:supersedes?|replaces?|updates?\s+and\s+replaces?|"
    r"previously\s+(?:published|recommended)|earlier\s+guidelines?)\b",
    re.IGNORECASE,
)


def load_kept_documents() -> list[dict[str, Any]]:
    manifest = json.loads(
        (CORPUS_DIR / "corpus_manifest.json").read_text(encoding="utf-8")
    )
    return [doc for doc in manifest["documents"] if doc["status"] == "ok"]


def split_pages(text: str) -> dict[int, str]:
    matches = list(PAGE_MARK_RE.finditer(text))
    pages: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages[int(match.group(1))] = text[start:end]
    return pages


def strip_watermarks(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not WATERMARK_RE.search(line)
    )


def ga_hits(page_text: str) -> int:
    return (
        len(GA_PLUS_RE.findall(page_text))
        + len(GA_WEEKS_RE.findall(page_text))
        + len(GA_WINDOW_RE.findall(page_text))
        + len(GESTATION_PHRASE_RE.findall(page_text))
    )


def run_prescan() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for doc in load_kept_documents():
        raw = (CORPUS_DIR / doc["input_file"]).read_text(encoding="utf-8")
        pages = split_pages(raw)
        cleaned_pages = {n: strip_watermarks(body) for n, body in pages.items()}
        text = "\n\n".join(cleaned_pages.values())
        chars = len(text)
        counts = {
            "ga_plus": len(GA_PLUS_RE.findall(text)),
            "ga_weeks": len(GA_WEEKS_RE.findall(text)),
            "ga_window": len(GA_WINDOW_RE.findall(text)),
            "gestation_phrase": len(GESTATION_PHRASE_RE.findall(text)),
            "population_terms": len(POPULATION_RE.findall(text)),
            "parameter_terms": len(PARAMETER_RE.findall(text)),
            "plane_terms": len(PLANE_RE.findall(text)),
            "supersession_terms": len(SUPERSESSION_RE.findall(text)),
        }
        rows.append(
            {
                "source_id": doc["source_id"],
                "pages": len(pages),
                "chars": chars,
                "ga_mentions_per_10k": round(
                    10_000
                    * (
                        counts["ga_plus"]
                        + counts["ga_weeks"]
                        + counts["ga_window"]
                        + counts["gestation_phrase"]
                    )
                    / chars,
                    2,
                ),
                **counts,
            }
        )
    total_chars = sum(row["chars"] for row in rows)
    summary = {
        "articles": len(rows),
        "total_chars": total_chars,
        "total_pages": sum(row["pages"] for row in rows),
        "ga_mention_total": sum(
            row["ga_plus"] + row["ga_weeks"] + row["ga_window"] + row["gestation_phrase"]
            for row in rows
        ),
        "population_term_total": sum(row["population_terms"] for row in rows),
        "supersession_article_count": sum(
            1 for row in rows if row["supersession_terms"] > 0
        ),
        "ga_per_10k_median": sorted(row["ga_mentions_per_10k"] for row in rows)[
            len(rows) // 2
        ],
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "condition_density_prescan.json").write_text(
        json.dumps({"summary": summary, "articles": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        f"\n{'source_id':<58} {'pages':>5} {'ga/10k':>7} {'pop':>5} {'sup':>4}"
    )
    for row in sorted(rows, key=lambda r: -r["ga_mentions_per_10k"]):
        print(
            f"{row['source_id']:<58} {row['pages']:>5} "
            f"{row['ga_mentions_per_10k']:>7} {row['population_terms']:>5} "
            f"{row['supersession_terms']:>4}"
        )
    return {"summary": summary, "articles": rows}


def pick_pages() -> dict[str, Any]:
    rng = random.Random(SEED)
    sampling: list[dict[str, Any]] = []
    for doc in load_kept_documents():
        raw = (CORPUS_DIR / doc["input_file"]).read_text(encoding="utf-8")
        pages = split_pages(raw)
        cleaned = {n: strip_watermarks(body) for n, body in pages.items()}
        ranked = sorted(cleaned, key=lambda n: (-ga_hits(cleaned[n]), n))
        chosen: dict[int, str] = {}
        for page_no in ranked[:2]:
            if ga_hits(cleaned[page_no]) > 0:
                chosen[page_no] = "mining"
        unbiased_page = rng.choice(sorted(cleaned))
        chosen.setdefault(unbiased_page, "unbiased")
        for page_no, purpose in sorted(chosen.items()):
            sampling.append(
                {
                    "sample_id": f"{doc['source_id']}#p{page_no}#{purpose}",
                    "source_id": doc["source_id"],
                    "page": page_no,
                    "purpose": purpose,
                    "text": cleaned[page_no],
                }
            )
    out = RESULTS_DIR / "density_sampling.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"seed": SEED, "pages": sampling}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    mining = sum(1 for item in sampling if item["purpose"] == "mining")
    unbiased = sum(1 for item in sampling if item["purpose"] == "unbiased")
    print(f"sampled pages: {len(sampling)} (mining={mining}, unbiased={unbiased})")
    print(f"-> {out}")
    return {"pages": len(sampling), "mining": mining, "unbiased": unbiased}


def normalize_topic(topic: str) -> str:
    words = re.findall(r"[a-z]+", topic.lower())
    stop = {
        "the", "a", "an", "of", "in", "for", "and", "or", "to", "with", "on",
        "is", "are", "be", "should", "at", "by", "from", "fetal", "foetal",
        "pregnancy", "women", "woman", "patient", "patients", "scan",
    }
    return " ".join(w for w in words if w not in stop)


def run_analyze(statements_path: Path, out_path: Path | None) -> dict[str, Any]:
    payload = json.loads(statements_path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for sample in payload["extractions"]:
        for statement in sample["statements"]:
            records.append(
                {
                    "sample_id": sample["sample_id"],
                    "purpose": sample["sample_id"].split("#")[-1],
                    **statement,
                }
            )

    def has_ga(statement: dict[str, Any]) -> bool:
        ga = statement.get("ga_weeks") or {}
        return bool(ga.get("min") is not None or ga.get("max") is not None)

    def has_conditions(statement: dict[str, Any]) -> bool:
        return has_ga(statement) or bool(statement.get("conditions"))

    total = len(records)
    with_ga = sum(1 for r in records if has_ga(r))
    with_any = sum(1 for r in records if has_conditions(r))
    type_counts = Counter(r.get("conditional_type", "none") for r in records)

    # Unbiased per-page rate -> corpus extrapolation (order-of-magnitude).
    manifest_docs = load_kept_documents()
    pages_by_source = {doc["source_id"]: doc["page_count"] for doc in manifest_docs}
    unbiased = [r for r in records if r["purpose"] == "unbiased"]
    per_article_rates = {
        source_id: sum(
            1 for r in unbiased if r["sample_id"].startswith(f"{source_id}#")
        )
        for source_id in pages_by_source
    }
    extrapolated_low = sum(
        rate * pages_by_source[source_id]
        for source_id, rate in per_article_rates.items()
        if rate > 0
    )
    articles_with_zero = sum(1 for rate in per_article_rates.values() if rate == 0)

    # Condition-variant groups from the mining set.  Topic token clustering:
    # exact-string grouping almost never merges paraphrased topics.
    mining_records = [
        record
        for record in records
        if record["purpose"] == "mining" and (record.get("topic") or "").strip()
    ]
    clusters: list[list[dict[str, Any]]] = []
    for record in mining_records:
        tokens = set(normalize_topic(record["topic"]).split())
        best_index: int | None = None
        best_score = 0.0
        for index, cluster in enumerate(clusters):
            seed_tokens = set(normalize_topic(cluster[0]["topic"]).split())
            union = tokens | seed_tokens
            score = len(tokens & seed_tokens) / len(union) if union else 0.0
            if score > best_score:
                best_index, best_score = index, score
        if best_index is not None and best_score >= 0.6:
            clusters[best_index].append(record)
        else:
            clusters.append([record])

    def signature(member: dict[str, Any]) -> tuple[Any, ...]:
        ga = member.get("ga_weeks") or {}
        return (
            ga.get("min"),
            ga.get("max"),
            frozenset(member.get("conditions") or []),
        )

    variant_groups: list[dict[str, Any]] = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        signatures = {signature(member) for member in cluster}
        if len(signatures) < 2:
            continue
        ga_windows = {
            (signature(member)[0], signature(member)[1])
            for member in cluster
            if has_ga(member)
        }
        population_sets = {
            signature(member)[2]
            for member in cluster
            if has_ga(member) and member.get("conditions")
        }
        technique_sets = {
            signature(member)[2]
            for member in cluster
            if not has_ga(member) and member.get("conditions")
        }
        variant_groups.append(
            {
                "topic": normalize_topic(cluster[0]["topic"]),
                "members": len(cluster),
                "distinct_ga_windows": len(ga_windows),
                "distinct_population_sets": len(population_sets),
                "distinct_technique_sets": len(technique_sets),
                "articles": len({m["sample_id"].split("#")[0] for m in cluster}),
                "example_topics": sorted({m.get("topic", "") for m in cluster})[:3],
            }
        )
    variant_groups.sort(key=lambda g: (-g["members"], g["topic"]))

    analysis = {
        "total_statements": total,
        "with_ga_condition": with_ga,
        "with_any_condition": with_any,
        "conditional_type_counts": dict(type_counts),
        "unbiased_pages": len({r["sample_id"] for r in unbiased}),
        "unbiased_condition_bearing_statements": sum(
            1 for r in unbiased if has_conditions(r)
        ),
        "extrapolated_condition_statements_point": extrapolated_low,
        "unbiased_zero_articles": articles_with_zero,
        "mining_clusters_total": len(clusters),
        "condition_variant_groups": len(variant_groups),
        "variant_groups_top": variant_groups[:20],
    }
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps({k: v for k, v in analysis.items() if k != "variant_groups_top"}, ensure_ascii=False, indent=2))
    for group in analysis["variant_groups_top"][:10]:
        print(
            f"  - {group['topic']}: members={group['members']} "
            f"ga_windows={group['distinct_ga_windows']} "
            f"pop_sets={group['distinct_population_sets']} "
            f"tech_sets={group['distinct_technique_sets']} articles={group['articles']}"
        )
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    sub.add_parser("prescan")
    sample_parser = sub.add_parser("sample")
    sample_parser.add_argument("--out", type=Path, default=RESULTS_DIR / "density_sampling.json")
    analyze_parser = sub.add_parser("analyze")
    analyze_parser.add_argument("--statements", type=Path, required=True)
    analyze_parser.add_argument("--out", type=Path, default=RESULTS_DIR / "density_analysis.json")
    args = parser.parse_args()

    if args.phase == "prescan":
        run_prescan()
    elif args.phase == "sample":
        pick_pages()
    else:
        run_analyze(args.statements, args.out)


if __name__ == "__main__":
    main()
