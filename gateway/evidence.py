"""Source-bound hypotheses. Text extraction alone never establishes completion."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class SourceDocument(StrictModel):
    source_id: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=50000)
    effective_at: str
    received_at: str

    @model_validator(mode='after')
    def timestamps(self):
        for value in (self.effective_at, self.received_at):
            if datetime.fromisoformat(value.replace('Z', '+00:00')).utcoffset() is None:
                raise ValueError('Source timestamps require timezones')
        return self

    @property
    def content_sha256(self):
        return hashlib.sha256(self.text.encode()).hexdigest()


class Candidate(StrictModel):
    input_lot: str = Field(pattern=r'^[A-Z0-9][A-Z0-9-]{0,63}$')
    output_lot: str = Field(pattern=r'^[A-Z0-9][A-Z0-9-]{0,63}$')
    quote: str = Field(min_length=1, max_length=4000)


class CandidateBatch(StrictModel):
    candidates: list[Candidate] = Field(max_length=30)


class Locator(StrictModel):
    kind: Literal['text_span'] = 'text_span'
    unit: Literal['unicode_codepoint'] = 'unicode_codepoint'
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class SourcePointer(StrictModel):
    source_id: str
    source_version: str
    content_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    locator: Locator
    effective_at: str
    received_at: str


class ProposedClaim(StrictModel):
    claim_id: str
    input_lot: str
    output_lot: str
    predicate: Literal['PROPOSED_INPUT_TO'] = 'PROPOSED_INPUT_TO'
    status: Literal['PROPOSED'] = 'PROPOSED'
    validation_basis: Literal['EXACT_SOURCE_SPAN_ONLY'] = 'EXACT_SOURCE_SPAN_ONLY'
    quote: str
    source: SourcePointer
    extraction_receipt_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def identity(self):
        fields = self.model_dump(exclude={'claim_id'})
        if self.claim_id != 'claim-' + digest(fields):
            raise ValueError('Claim content does not match its immutable identity')
        return self


def bind_candidate(candidate: Candidate, document: SourceDocument, extraction_digest: str) -> ProposedClaim:
    quote = candidate.quote
    start = document.text.find(quote)
    if start < 0 or document.text.find(quote, start + 1) >= 0:
        raise ValueError('Candidate quote is missing or ambiguous')
    if not all(has_identifier(quote, lot) for lot in (candidate.input_lot, candidate.output_lot)):
        raise ValueError('Candidate identifiers are not present in the cited span')
    if candidate.input_lot == candidate.output_lot:
        raise ValueError('Self-link is not a material proposal')
    source = SourcePointer(source_id=document.source_id, source_version=document.source_version,
                           content_sha256=document.content_sha256,
                           locator=Locator(start=start, end=start + len(quote)),
                           effective_at=document.effective_at, received_at=document.received_at)
    fields = {'input_lot': candidate.input_lot, 'output_lot': candidate.output_lot,
              'predicate': 'PROPOSED_INPUT_TO', 'status': 'PROPOSED',
              'validation_basis': 'EXACT_SOURCE_SPAN_ONLY', 'quote': quote,
              'source': source.model_dump(), 'extraction_receipt_sha256': extraction_digest}
    return ProposedClaim(claim_id='claim-' + digest(fields), **fields)


def has_identifier(text: str, identifier: str) -> bool:
    return re.search(r'(?<![A-Za-z0-9-])' + re.escape(identifier) + r'(?![A-Za-z0-9-])', text) is not None


def locate_candidate(candidate: Candidate, document: SourceDocument) -> tuple[Candidate, bool]:
    """Resolve a unique source sentence for Cognee's proposed ID pair.

    This is only a locator: co-occurrence cannot corroborate the relationship.
    The rejected generated quote remains in the extraction receipt.
    """
    if (document.text.count(candidate.quote) == 1
            and all(has_identifier(candidate.quote, lot) for lot in (candidate.input_lot, candidate.output_lot))):
        return candidate, False
    spans = [m.group().strip() for m in re.finditer(r'[^.!?\n]+[.!?]?', document.text)
             if all(has_identifier(m.group(), lot) for lot in (candidate.input_lot, candidate.output_lot))]
    if len(spans) != 1:
        raise ValueError('No unique source sentence for the proposed identifiers')
    return Candidate(input_lot=candidate.input_lot, output_lot=candidate.output_lot, quote=spans[0]), True
