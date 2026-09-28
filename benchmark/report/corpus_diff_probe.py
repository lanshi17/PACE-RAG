"""P3 corpus diff probe: duplicate-pair disambiguation and version-chain check.

Reads the unified corpus texts and compares the six known duplicate pairs
(four same-article pairs under different source_ids, two multi-version pairs
under one source_id) plus a light surface check of the fetal-MRI 2017->2023
version chain.  Read-only: prints a summary and optionally writes a JSON
artifact.  Standard library only.

Usage:
    python benchmark/report/corpus_diff_probe.py [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "benchmark" / "data" / "corpus" / "input"

# (kept-name-hint, file_a, file_b) -- exact input/*.txt names from the manifest.
PAIRS: dict[str, tuple[str, str]] = {
    "midtrimester-2022": (
        "ISUOG-midtrimester-2022--8bdd61850954.txt",
        "ISUOG-Practice-Guidelines-routine-mid-trimester-fetal-ultrasound--182ace79c14c.txt",
    ),
    "intrapartum-2018": (
        "ISUOG_2018_intrapartum-ultrasound--33694eca76f0.txt",
        "ISUOG-Practice-Guidelines-intrapartum-ultrasound--026fc4b45720.txt",
    ),
    "biometry-2019": (
        "ISUOG_2019_fetal-biometry-growth--695f6e9d10a1.txt",
        "ISUOG-Practice-Guidelines-ultrasound-fetal-biometry-growth--36ec9024bdf7.txt",
    ),
    "invasive-2016": (
        "ISUOG_2016_invasive-prenatal-diagnosis--73c6027ffd5a.txt",
        "ISUOG-Practice-Guidelines-invasive-procedures-prenatal-diagnosis--9bea25437140.txt",
    ),
    "cns-part1-2020": (
        "ISUOG-cns-2020--176327e1a47a.txt",
        "ISUOG-cns-2020--e8854d551b9d.txt",
    ),
    "cardiac-2023": (
        "ISUOG-fetal-cardiac-screening-2023--3b9efcc7cfe1.txt",
        "ISUOG-fetal-cardiac-screening-2023--932fdca0dac6.txt",
    ),
}

MRI_CHAIN = (
    "ISUOG-Practice-Guidelines-fetal-MRI--e1f6ec8ed154.txt",
    "Updated-ISUOG-Practice-Guidelines-performance-of-fetal-magnetic-resonance-1--3b924de5b1d7.txt",
)

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
PAGE_MARK_RE = re.compile(r"^## Page (\d+)\s*$", re.MULTILINE)
CITATION_LINE_RE = re.compile(r"Ultrasound Obstet Gynecol[^\n]*")
SECTION_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})*)\.?\s+([A-Z][^\n]{3,90})$", re.MULTILINE)
GA_PLUS_RE = re.compile(r"\b\d{1,2}\s*\+\s*\d\b")
GA_WEEKS_RE = re.compile(r"\b\d{1,2}(?:\.\d)?\s+weeks\b")
REC_RE = re.compile(r"\b(?:should(?:\s+not)?\s+be|we\s+recommend|is\s+recommended)\b", re.IGNORECASE)


def split_pages(text: str) -> dict[int, str]:
    """Split a corpus text into {page_number: page_body} using the markers."""
    matches = list(PAGE_MARK_RE.finditer(text))
    pages: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages[int(match.group(1))] = text[start:end]
    return pages


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def word_shingles(text: str, k: int = 5) -> set[str]:
    words = text.split()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def first_page(text: str) -> str:
    pages = split_pages(text)
    return pages.get(1, text[:6000])


def find_doi(text: str) -> str | None:
    match = DOI_RE.search(first_page(text))
    return match.group(0).rstrip(".") if match else None


def find_citation_line(text: str) -> str | None:
    match = CITATION_LINE_RE.search(first_page(text))
    return match.group(0).strip() if match else None


def first_diff_snippet(a: str, b: str, window: int = 150) -> str:
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            lo_a = max(0, i1 - window)
            lo_b = max(0, j1 - window)
            return (
                f"[{tag}] ...{a[lo_a:i2 + window]!r} || ...{b[lo_b:j2 + window]!r}"
            )
    return ""


def compare_pair(name: str, file_a: str, file_b: str) -> dict[str, Any]:
    text_a = (DEFAULT_INPUT / file_a).read_text(encoding="utf-8")
    text_b = (DEFAULT_INPUT / file_b).read_text(encoding="utf-8")
    pages_a, pages_b = split_pages(text_a), split_pages(text_b)
    norm_a, norm_b = normalize(text_a), normalize(text_b)

    sh_a, sh_b = word_shingles(norm_a), word_shingles(norm_b)
    global_jaccard = jaccard(sh_a, sh_b)

    page_ratios: dict[int, float] = {}
    if len(pages_a) == len(pages_b):
        for page_no in sorted(pages_a):
            ratio = SequenceMatcher(
                None, normalize(pages_a[page_no]), normalize(pages_b[page_no]), autojunk=False
            ).ratio()
            page_ratios[page_no] = round(ratio, 4)
    weak_pages = sorted((p for p, r in page_ratios.items() if r < 0.99), key=lambda p: page_ratios[p])
    worst = weak_pages[:3]
    snippets = {
        str(p): first_diff_snippet(normalize(pages_a[p]), normalize(pages_b[p]))
        for p in worst
    }

    return {
        "pair": name,
        "file_a": file_a,
        "file_b": file_b,
        "doi_a": find_doi(text_a),
        "doi_b": find_doi(text_b),
        "citation_a": find_citation_line(text_a),
        "citation_b": find_citation_line(text_b),
        "pages_a": len(pages_a),
        "pages_b": len(pages_b),
        "chars_a": len(norm_a),
        "chars_b": len(norm_b),
        "shingle_jaccard": round(global_jaccard, 4),
        "pages_below_0_99": weak_pages,
        "min_page_ratio": min(page_ratios.values()) if page_ratios else None,
        "worst_page_snippets": snippets,
    }


def surface_check_chain(name: str, file_old: str, file_new: str) -> dict[str, Any]:
    text_old = (DEFAULT_INPUT / file_old).read_text(encoding="utf-8")
    text_new = (DEFAULT_INPUT / file_new).read_text(encoding="utf-8")

    def sections(text: str) -> set[str]:
        found = set()
        for number, title in SECTION_RE.findall(text):
            found.add(f"{number} {normalize(title)}")
        return found

    sec_old, sec_new = sections(text_old), sections(text_new)

    def rec_count(text: str) -> int:
        return len(REC_RE.findall(text))

    return {
        "chain": name,
        "doi_old": find_doi(text_old),
        "doi_new": find_doi(text_new),
        "citation_old": find_citation_line(text_old),
        "citation_new": find_citation_line(text_new),
        "sections_old": len(sec_old),
        "sections_new": len(sec_new),
        "sections_shared": len(sec_old & sec_new),
        "section_jaccard": round(jaccard(sec_old, sec_new), 4),
        "rec_mentions_old": rec_count(text_old),
        "rec_mentions_new": rec_count(text_new),
        "ga_plus_old": len(GA_PLUS_RE.findall(text_old)),
        "ga_plus_new": len(GA_PLUS_RE.findall(text_new)),
        "ga_weeks_old": len(GA_WEEKS_RE.findall(text_old)),
        "ga_weeks_new": len(GA_WEEKS_RE.findall(text_new)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="write full results JSON here")
    args = parser.parse_args()

    pair_results = [compare_pair(name, fa, fb) for name, (fa, fb) in PAIRS.items()]
    chain_results = [surface_check_chain("fetal-mri-2017-2023", MRI_CHAIN[0], MRI_CHAIN[1])]

    for result in pair_results:
        print(f"\n=== {result['pair']} ===")
        print(f"  doi   a={result['doi_a']}  b={result['doi_b']}")
        print(f"  cite  a={result['citation_a']}")
        print(f"        b={result['citation_b']}")
        print(
            f"  pages a={result['pages_a']} b={result['pages_b']}  "
            f"chars a={result['chars_a']} b={result['chars_b']}"
        )
        print(f"  shingle_jaccard={result['shingle_jaccard']}")
        print(f"  pages<0.99: {result['pages_below_0_99'] or 'none'}")
        if result["min_page_ratio"] is not None:
            print(f"  min_page_ratio={result['min_page_ratio']}")
        for page, snippet in result["worst_page_snippets"].items():
            print(f"  worst p{page}: {snippet[:400]}")

    for result in chain_results:
        print(f"\n=== chain {result['chain']} ===")
        print(f"  doi old={result['doi_old']}  new={result['doi_new']}")
        print(f"  cite old={result['citation_old']}")
        print(f"       new={result['citation_new']}")
        print(
            f"  sections old={result['sections_old']} new={result['sections_new']} "
            f"shared={result['sections_shared']} jaccard={result['section_jaccard']}"
        )
        print(
            f"  rec mentions old={result['rec_mentions_old']} new={result['rec_mentions_new']}  "
            f"GA+ old={result['ga_plus_old']} new={result['ga_plus_new']}  "
            f"weeks old={result['ga_weeks_old']} new={result['ga_weeks_new']}"
        )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"pairs": pair_results, "chains": chain_results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nresults -> {args.json}")


if __name__ == "__main__":
    main()
