"""Gate 0 probe: publish a validated claim into HydraDB and read it back.

This is the second half of the Cognee->HydraDB bridge (SPEC.md 6.3). The first
half (probes/cognee_provenance.py) produces a source pointer we trust because we
validated the quote against our own immutable copy. This half stores it and
proves it survives a query.

The metadata shape below is not obvious and was found by bisection against the
live API. Constraints that matter, all discovered the hard way:

  - `document_metadata` must be a JSON *array*, one object per document.
  - `source_id` is REQUIRED in every item. Omitting it yields the misleading
    error "each item must be a JSON object of per-document metadata".
  - `additional_metadata` must be a nested object, never a JSON string.
  - Reserved keys are rejected RECURSIVELY, so a nested `source_id` inside
    `additional_metadata` is refused too. SPEC.md 5.1 names a pointer field
    `source_id`, so it must be renamed on the way in.
  - `additional_metadata` allows a maximum nesting depth of 1, so the pointer's
    `locator` object has to be flattened into scalars.
  - Ingestion is asynchronous. A 202 means queued, not indexed.

Run:  python probes/hydradb_bridge.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hydra_db import HydraDB

from probes.cognee_provenance import SourceDocument, build_source_pointer

DATABASE = "gate0probe"
COLLECTION = "bridge_demo"


def flatten_pointer(pointer: dict, claim_state: str, quote: str) -> dict:
    """Map a SPEC.md 5.1 source pointer into HydraDB's metadata constraints."""
    return {
        "ptr_source_id": pointer["source_id"],  # renamed: `source_id` is reserved
        "ptr_source_version": pointer["source_version"],
        "ptr_sha256": pointer["content_sha256"],
        "ptr_locator_kind": pointer["locator"]["kind"],  # flattened: depth cap is 1
        "ptr_span_start": pointer["locator"]["start"],
        "ptr_span_end": pointer["locator"]["end"],
        "ptr_effective_at": pointer["effective_at"],
        "claim_state": claim_state,
        "quote": quote,
    }


def main() -> None:
    client = HydraDB(token=os.environ["HYDRA_DB_API_KEY"])

    doc = SourceDocument(
        source_id="NOTE-017",
        source_version="2",
        text=(
            "Work order WO-5512 at PLANT-A completed on 2026-03-04. "
            "Lot INT-1000 consumed ingredient ING-041."
        ),
        effective_at="2026-03-04T00:00:00Z",
    )
    quote = "Lot INT-1000 consumed ingredient ING-041."

    pointer = build_source_pointer(quote, doc, datetime.now(timezone.utc).isoformat())
    if pointer is None:
        raise SystemExit("quote did not validate against the source; refusing to publish")

    metadata = [
        {
            "source_id": doc.source_id,
            "evidence_subject": "INT-1000",
            "id": f"{doc.source_id}-v{doc.source_version}",
            "additional_metadata": flatten_pointer(pointer, "SUPPORTED", quote),
        }
    ]

    client.context.ingest(
        database=DATABASE,
        collection=COLLECTION,
        type="knowledge",
        documents=(f"{doc.source_id}.txt", doc.text.encode(), "text/plain"),
        document_metadata=json.dumps(metadata),
    )
    print("ingest accepted (202) - queued, not yet indexed")

    time.sleep(25)  # TODO: poll /context/status until indexing_status is terminal

    result = client.query(
        database=DATABASE,
        collection=COLLECTION,
        query="What did lot INT-1000 consume?",
        max_results=3,
    )
    data = (result.dict() if hasattr(result, "dict") else result)["data"]

    for chunk in data["chunks"]:
        meta = chunk["additional_metadata"]
        print(f"\nchunk       : {chunk['chunk_content']}")
        print(f"relevancy   : {chunk['relevancy_score']:.4f}")
        print(f"pointer     : {meta['ptr_source_id']} v{meta['ptr_source_version']} "
              f"span[{meta['ptr_span_start']}:{meta['ptr_span_end']}]")
        # The stored span must still resolve against our immutable copy.
        excerpt = doc.text[meta["ptr_span_start"] : meta["ptr_span_end"]]
        print(f"round-trip  : {excerpt == meta['quote']}  ({excerpt!r})")


if __name__ == "__main__":
    main()
