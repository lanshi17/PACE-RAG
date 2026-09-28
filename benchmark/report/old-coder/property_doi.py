"""Property layer: invariants of extract_page1_doi (hypothesis, ephemeral dep).

P1  A DOI printed on page 1 is always returned verbatim (trailing period
    stripped), no matter what later pages contain; repeated calls agree.
P2  A DOI that appears only after page 1 is never returned.
P3  Page-1 content without a DOI yields None even when it looks DOI-adjacent
    (the junk alphabet deliberately contains digits and dots but no slash).
P4  Arbitrary unicode junk never raises; the result is a string or None.

Run by gauntlet.sh as:  uv run --with hypothesis python \
    benchmark/report/old-coder/property_doi.py
"""

from __future__ import annotations

import string
import sys
from pathlib import Path

from hypothesis import given, settings, strategies as st  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from benchmark.common.corpus import extract_page1_doi  # noqa: E402

LINE_ALPHABET = string.ascii_letters + string.digits + " .;:()-"
DOIS = ["10.1002/uog.24888", "10.1234/abc.123", "10.5555/x-y(1).2"]

line = st.text(alphabet=LINE_ALPHABET, max_size=80)
page_lines = st.lists(line, max_size=8)
pages = st.lists(page_lines, min_size=1, max_size=4)
doi = st.sampled_from(DOIS)


def corpus_text(pages_content: list[list[str]]) -> str:
    body = "\n\n".join(
        f"## Page {number}\n\n" + "\n".join(lines)
        for number, lines in enumerate(pages_content, start=1)
    )
    return f"SOURCE_ID: x\nPDF_SHA256: ab\n\n{body}\n"


@settings(max_examples=150, deadline=None)
@given(pages=pages, doi=doi)
def property_doi_on_page1_always_found(pages: list[list[str]], doi: str) -> None:
    first = [f"cite {doi} end", "title line"]
    result = extract_page1_doi(corpus_text([first, *pages]))
    assert result == doi, f"expected {doi!r}, got {result!r}"
    assert extract_page1_doi(corpus_text([first, *pages])) == result


@settings(max_examples=150, deadline=None)
@given(pages=pages, doi=doi)
def property_doi_after_page1_ignored(pages: list[list[str]], doi: str) -> None:
    text = corpus_text([*pages, [f"DOI: {doi}"]])
    result = extract_page1_doi(text)
    assert result is None, f"later-page DOI leaked: {result!r}"


@settings(max_examples=150, deadline=None)
@given(first=page_lines, tail=pages)
def property_page1_without_doi_is_none(
    first: list[str], tail: list[list[str]]
) -> None:
    result = extract_page1_doi(corpus_text([first, *tail]))
    assert result is None, f"unexpected DOI from junk: {result!r}"


@settings(max_examples=200, deadline=None)
@given(junk=st.text(max_size=400))
def property_arbitrary_junk_never_raises(junk: str) -> None:
    result = extract_page1_doi(f"SOURCE_ID: x\n\n## Page 1\n\n{junk}")
    assert result is None or isinstance(result, str)


def main() -> int:
    checks = [
        property_doi_on_page1_always_found,
        property_doi_after_page1_ignored,
        property_page1_without_doi_is_none,
        property_arbitrary_junk_never_raises,
    ]
    failures = 0
    for check in checks:
        try:
            check()
            print(f"  property {check.__name__}: ok")
        except Exception as exc:  # noqa: BLE001
            print(f"  property {check.__name__}: FALSIFIED - {exc}")
            failures += 1
    if failures:
        print(f"property layer FAILED ({failures} falsified)")
        return 1
    print(f"property layer: {len(checks)}/{len(checks)} properties held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
