"""Unit tests with explicitly MOCKED sponsors; not acceptance-gate evidence."""
import json
import unittest
from unittest.mock import AsyncMock

import httpx
from pydantic import ValidationError

from gateway.cognee import ExtractionFailure, parse_extraction
from gateway.evidence import Candidate, SourceDocument, ProposedClaim, bind_candidate, digest, locate_candidate
from gateway.hydradb import GraphFailure, GraphTransport, ProposalReader, ProposalWriter


def document(text='Lot RET-731 may enter MIX-842.'):
    return SourceDocument(source_id='NOTE-1', source_version='1', text=text,
                          effective_at='2026-09-11T00:00:00Z', received_at='2026-09-11T01:00:00Z')


def proposal():
    doc = document()
    return bind_candidate(Candidate(input_lot='RET-731', output_lot='MIX-842', quote=doc.text), doc, '0' * 64)


class SourceBindingTests(unittest.TestCase):
    def test_exact_text_is_only_proposed_and_keeps_full_pointer(self):
        claim = proposal()
        self.assertEqual(claim.status, 'PROPOSED')
        self.assertEqual(claim.source.received_at, document().received_at)
        data = claim.model_dump()
        data['status'] = 'SUPPORTED'
        with self.assertRaises(ValidationError):
            ProposedClaim.model_validate(data)
        with self.assertRaises(ValidationError):
            Candidate(input_lot='RET-731', output_lot='MIX-842', quote=document().text, confidence=1.0)

    def test_paraphrase_rejected_then_explicitly_located_as_hypothesis(self):
        candidate = Candidate(input_lot='RET-731', output_lot='MIX-842', quote='RET-731 was consumed in MIX-842.')
        with self.assertRaises(ValueError):
            bind_candidate(candidate, document(), '0' * 64)
        located, repaired = locate_candidate(candidate, document())
        self.assertTrue(repaired)
        claim = bind_candidate(located, document(), '0' * 64)
        self.assertEqual(claim.quote, document().text)
        self.assertEqual(claim.status, 'PROPOSED')

    def test_ambiguous_missing_and_prefix_ids_cannot_bind(self):
        candidate = Candidate(input_lot='RET-731', output_lot='MIX-842', quote='generated')
        for text in ['RET-731 may enter MIX-842. RET-731 may leave MIX-842.',
                     'RET-7310 may enter MIX-842.', 'RET-731 may enter MIX-8420.',
                     'No relevant material.']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                locate_candidate(candidate, document(text))

    def test_evidence_tampering_changes_identity(self):
        data = proposal().model_dump()
        data['source']['received_at'] = '2026-09-12T00:00:00Z'
        with self.assertRaises(ValidationError):
            ProposedClaim.model_validate(data)

    def test_cognee_dataset_and_schema_are_enforced(self):
        valid = [{'dataset_id': 'dataset-a', 'search_result': [json.dumps({'candidates': []})]}]
        self.assertEqual(parse_extraction(valid, 'dataset-a').candidates, [])
        for invalid in [[], valid * 2, [{'dataset_id': 'dataset-b', 'search_result': ['{}']}],
                        [{'dataset_id': 'dataset-a', 'search_result': ['not json']}]]:
            with self.assertRaises(ExtractionFailure):
                parse_extraction(invalid, 'dataset-a')


class GraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_does_not_turn_malformed_or_failed_response_into_empty_success(self):
        for status, body in [(200, {'success': True, 'data': {}, 'meta': {'request_id': 'MOCK'}}),
                             (200, {'success': False, 'data': []}), (503, {'error': 'MOCK failure'})]:
            async def handler(request):
                return httpx.Response(status, json=body)
            transport = GraphTransport('MOCK-token', 'test-db', client=httpx.AsyncClient(
                base_url='https://mock.invalid', transport=httpx.MockTransport(handler)))
            with self.assertRaises(GraphFailure):
                await transport.execute('collection', 'RETURN $v', {'v': 'input'})
            await transport.close()

    async def test_write_and_paging_content_contract(self):
        first = proposal()
        doc = document('Lot MIX-842 may enter PACK-953.')
        second = bind_candidate(Candidate(input_lot='MIX-842', output_lot='PACK-953', quote=doc.text), doc, '0'*64)
        mock = AsyncMock()
        mock.database = 'MOCK-db'
        mock.execute.return_value = {'rows': [{'written': 2}]}
        publication, _ = await ProposalWriter(mock).publish([first, second])
        written_query = mock.execute.call_args.args[1]
        self.assertNotIn('RET-731', written_query)
        ordered = sorted([first, second], key=lambda c: c.claim_id)
        mock.execute.side_effect = [
            {'rows': [{'claim_json': ordered[0].model_dump_json()}]},
            {'rows': [{'claim_json': ordered[1].model_dump_json()}]},
        ]
        result = await ProposalReader(mock).read(publication, page_size=1)
        self.assertTrue(result['coverage']['delivery_complete'])
        self.assertFalse(result['coverage']['complete'])
        self.assertEqual(mock.execute.call_args.args[2]['offset'], 1)
        mock.execute.side_effect = [{'rows': [{'claim_json': ordered[0].model_dump_json()}]}]
        limited = await ProposalReader(mock).read(publication, page_size=1, max_pages=1)
        self.assertFalse(limited['coverage']['delivery_complete'])
        self.assertEqual(limited['coverage']['incomplete_reason'], 'page_budget_exhausted')
        mock.execute.side_effect = [{'rows': []}]
        empty = await ProposalReader(mock).read(publication, page_size=1)
        self.assertFalse(empty['coverage']['delivery_complete'])

    async def test_duplicate_page_cannot_satisfy_manifest(self):
        first = proposal()
        mock = AsyncMock()
        mock.database = 'MOCK-db'
        mock.execute.return_value = {'rows': [{'written': 1}]}
        publication, _ = await ProposalWriter(mock).publish([first])
        mock.execute.return_value = {'rows': [{'claim_json': first.model_dump_json()},
                                            {'claim_json': first.model_dump_json()}]}
        result = await ProposalReader(mock).read(publication, page_size=2)
        self.assertFalse(result['coverage']['delivery_complete'])


if __name__ == '__main__':
    unittest.main()
