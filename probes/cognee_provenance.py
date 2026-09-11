"""Gate 0 probe: can we get SPEC.md 5.1 source pointers out of Cognee?

The problem this solves, established empirically (see memory.md 3):
  - Cognee's generated answer text rewrites identifiers with Unicode lookalikes
    (U+2011 for '-', U+202F for ' '), so `"ING-041" in answer` is False.
  - only_context=True returns verbatim source text but carries no references.
  - include_references=True returns ids but mangled text.
  - Passing both drops the references.

So no single Cognee call yields quote + locator together, which is exactly the
case SPEC.md 6.2.1 anticipates when it says a narrow custom task/pipeline is
required if default output does not preserve the required fields.

The approach here inverts the dependency: we never trust Cognee for the locator.
We own the immutable source, so we validate any candidate quote against our own
copy and compute the span ourselves. A quote that is not byte-exact in the source
never becomes a claim -- which is what catches the Unicode rewriting.
"""

import hashlib
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class SourceDocument:
    """An immutable evidence document. We own this, not Cognee."""

    source_id: str
    source_version: str
    text: str
    effective_at: str

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


# Characters models substitute for ASCII when they rewrite identifiers. NFKC alone
# is not enough: it maps U+2011 NON-BREAKING HYPHEN to U+2010 HYPHEN, which is
# still not ASCII '-', so the fold has to run after normalization.
_LOOKALIKES = {
    **{c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"},
    **{c: " " for c in "\u00a0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f"},
    **{c: "" for c in "\u200b\u200c\u200d\ufeff"},
}


def _fold(s: str) -> str:
    """Aggressively normalize lookalike punctuation to ASCII for comparison only."""
    return "".join(_LOOKALIKES.get(c, c) for c in unicodedata.normalize("NFKC", s))


@dataclass(frozen=True)
class ValidationResult:
    status: str  # VALIDATED | REJECTED_NORMALIZED_MISMATCH | REJECTED_NOT_FOUND | REJECTED_AMBIGUOUS
    span: Optional[tuple[int, int]] = None
    detail: str = ""


def validate_quote(quote: str, doc: SourceDocument) -> ValidationResult:
    """Locate a candidate quote in the immutable source.

    Byte-exact match is the only thing that validates. A quote that matches only
    after Unicode normalization is reported distinctly rather than accepted,
    because that is the signature of model-rewritten text rather than a real
    excerpt.
    """
    if not quote.strip():
        return ValidationResult("REJECTED_NOT_FOUND", detail="empty quote")

    occurrences = []
    start = doc.text.find(quote)
    while start != -1:
        occurrences.append(start)
        start = doc.text.find(quote, start + 1)

    if len(occurrences) == 1:
        s = occurrences[0]
        return ValidationResult("VALIDATED", (s, s + len(quote)))

    if len(occurrences) > 1:
        return ValidationResult(
            "REJECTED_AMBIGUOUS", detail=f"{len(occurrences)} occurrences; locator not unique"
        )

    # No exact hit. Distinguish "model rewrote the characters" from "not present".
    if _fold(quote) in _fold(doc.text):
        return ValidationResult(
            "REJECTED_NORMALIZED_MISMATCH",
            detail="matches only after Unicode normalization - generated text, not a verbatim excerpt",
        )

    return ValidationResult("REJECTED_NOT_FOUND", detail="quote absent from source")


def build_source_pointer(quote: str, doc: SourceDocument, received_at: str) -> Optional[dict]:
    """Emit the SPEC.md 5.1 source pointer, or None if the quote does not validate."""
    result = validate_quote(quote, doc)
    if result.status != "VALIDATED":
        return None
    return {
        "source_id": doc.source_id,
        "source_version": doc.source_version,
        "content_sha256": doc.content_sha256,
        "locator": {"kind": "text_span", "start": result.span[0], "end": result.span[1]},
        "effective_at": doc.effective_at,
        "received_at": received_at,
    }


if __name__ == "__main__":
    doc = SourceDocument(
        source_id="NOTE-017",
        source_version="2",
        text=(
            "Work order WO-5512 at PLANT-A completed on 2026-03-04. "
            "Lot INT-1000 consumed ingredient ING-041."
        ),
        effective_at="2026-03-04T00:00:00Z",
    )
    now = datetime.now(timezone.utc).isoformat()

    candidates = [
        ("verbatim excerpt (what only_context returns)", "Lot INT-1000 consumed ingredient ING-041."),
        ("model-rewritten (what the default answer returns)", "Lot\u202fINT\u20111000 consumed ingredient ING\u2011041."),
        ("hallucinated", "Lot INT-1000 consumed ingredient ING-999."),
    ]

    print(f"source {doc.source_id} v{doc.source_version}  sha256={doc.content_sha256[:16]}...\n")
    for label, quote in candidates:
        result = validate_quote(quote, doc)
        print(f"{label}\n  -> {result.status}  {result.detail}")
        pointer = build_source_pointer(quote, doc, now)
        print(f"  -> pointer: {asdict(result) if pointer is None else pointer['locator']}\n")
