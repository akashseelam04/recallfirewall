"""Fixed BYOG operations; no agent-facing Cypher or graph-writer endpoint.

Transport pinned to official CLI source commit
9dba30c2c9ca4f51f74e3f0e2d18e815998aec7f. Query receipts retain native metadata.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from gateway.evidence import ProposedClaim, digest


class GraphFailure(Exception):
    pass


@dataclass(frozen=True)
class Publication:
    collection: str
    manifest_sha256: str
    claim_count: int

    def __post_init__(self):
        if (not isinstance(self.manifest_sha256, str)
                or re.fullmatch(r'[0-9a-f]{64}', self.manifest_sha256) is None
                or self.collection != 'rf_' + self.manifest_sha256[:56]
                or type(self.claim_count) is not int or self.claim_count < 1):
            raise ValueError('Invalid graph publication')


class GraphTransport:
    def __init__(self, token: str, database: str, *, client: httpx.AsyncClient | None = None):
        self.database = database
        self.client = client or httpx.AsyncClient(base_url='https://api.hydradb.com',
                                                 timeout=30, follow_redirects=False)
        self.headers = {'Authorization': 'Bearer ' + token, 'API-Version': '2'}

    async def close(self):
        await self.client.aclose()

    async def execute(self, collection: str, query: str, parameters: dict) -> dict:
        body = {'database': self.database, 'collection': collection, 'query': query, 'params': parameters}
        if len(json.dumps(body).encode()) > 256 * 1024:
            raise GraphFailure('HydraDB request exceeds the graph request budget')
        try:
            response = await self.client.post('/byog/query', headers=self.headers, json=body)
            if response.status_code != 200:
                raise GraphFailure(f'HydraDB graph HTTP {response.status_code}; no fallback')
            payload = response.json()
            if (payload['success'] is not True or payload.get('error') is not None
                    or not isinstance(payload['data'], list)
                    or any(not isinstance(row, dict) for row in payload['data'])
                    or not isinstance(payload['meta']['request_id'], str)
                    or not payload['meta']['request_id']):
                raise ValueError()
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise GraphFailure('HydraDB graph transport or response contract failed') from None
        return {'rows': payload['data'], 'native_meta': payload['meta'],
                'database': self.database, 'collection': collection,
                'query': query, 'parameters': parameters}


class ProposalWriter:
    def __init__(self, transport: GraphTransport):
        self.transport = transport

    async def publish(self, claims: list[ProposedClaim]) -> tuple[Publication, dict]:
        if not claims or len({c.claim_id for c in claims}) != len(claims):
            raise ValueError('Publication requires nonempty, distinct source-bound claims')
        ordered = sorted((c.model_dump() for c in claims), key=lambda c: c['claim_id'])
        manifest = digest(ordered)
        publication = Publication('rf_' + manifest[:56], manifest, len(claims))
        rows = [{'claim_id': c['claim_id'], 'input_lot': c['input_lot'], 'output_lot': c['output_lot'],
                 'claim_json': json.dumps(c, sort_keys=True)} for c in ordered]
        receipt = await self.transport.execute(publication.collection, '''
UNWIND $claims AS row
MERGE (source:Lot {lot_id: row.input_lot})
MERGE (target:Lot {lot_id: row.output_lot})
MERGE (source)-[claim:PROPOSED_INPUT {claim_id: row.claim_id}]->(target)
SET claim.claim_json = row.claim_json
RETURN count(claim) AS written
'''.strip(), {'claims': rows})
        if (receipt['rows'] != [{'written': len(claims)}]
                or type(receipt['rows'][0]['written']) is not int):
            raise GraphFailure('HydraDB did not acknowledge the complete proposal write')
        return publication, receipt


class ProposalReader:
    def __init__(self, transport: GraphTransport):
        self.transport = transport

    async def read(self, publication: Publication, *, page_size: int = 20, max_pages: int = 30) -> dict:
        if (type(page_size) is not int or not 1 <= page_size <= 100
                or type(max_pages) is not int or not 1 <= max_pages <= 100):
            raise ValueError('Invalid graph retrieval budget')
        rows, receipts = [], []
        reason = 'page_budget_exhausted'
        for page in range(max_pages):
            receipt = await self.transport.execute(publication.collection, '''
MATCH ()-[claim:PROPOSED_INPUT]->()
RETURN claim.claim_json AS claim_json
ORDER BY claim.claim_id SKIP $offset LIMIT $limit
'''.strip(), {'offset': page * page_size, 'limit': page_size})
            receipts.append(receipt)
            try:
                claims = [ProposedClaim.model_validate_json(row['claim_json']) for row in receipt['rows']]
            except (KeyError, TypeError, ValueError):
                raise GraphFailure('HydraDB returned malformed proposal evidence') from None
            if len(claims) > page_size:
                raise GraphFailure('HydraDB exceeded the requested page size')
            rows.extend(c.model_dump() for c in claims)
            if len(rows) >= publication.claim_count or len(claims) < page_size:
                reason = 'manifest_or_count_mismatch'
                break
        # Completion is proven against the exact published content, not inferred
        # from an empty page, absent cursor, or the service's result preview.
        delivered = len(rows) == publication.claim_count and digest(rows) == publication.manifest_sha256
        return {'claims': rows, 'receipts': receipts,
                'coverage': {'rows': len(rows), 'scope': {'database': self.transport.database,
                                                        'collection': publication.collection},
                             'manifest_sha256': publication.manifest_sha256,
                             'delivery_complete': delivered, 'complete': False,
                             'snapshot_or_revision': None,
                             'incomplete_reason': 'incident_revision_not_committed' if delivered else reason}}

    async def candidate_descendants(self, publication: Publication, root_lot: str) -> dict:
        # Exploration only; these are proposal paths, never supported material paths.
        receipt = await self.transport.execute(publication.collection, '''
MATCH (root:Lot {lot_id: $root})-[:PROPOSED_INPUT*1..3]->(target:Lot)
RETURN DISTINCT target.lot_id AS lot_id ORDER BY lot_id LIMIT 100
'''.strip(), {'root': root_lot})
        return {'rows': receipt['rows'], 'receipt': receipt, 'status': 'PROPOSED',
                'coverage': {'complete': False, 'incomplete_reason': 'depth_3_and_row_100_budget'}}
