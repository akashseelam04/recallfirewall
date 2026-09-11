"""Live Cognee -> source-bound PROPOSED claims -> HydraDB BYOG -> new reader process.

Run `.venv/bin/python -m probes.graph_bridge` for a fresh sponsor pipeline.
`--captured-extraction PATH` resumes a recorded real Cognee response and states
that explicitly in its report; it does not pretend a second extraction ran.
"""
import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from gateway.cognee import CogneeExtractor, parse_extraction
from gateway.evidence import SourceDocument, bind_candidate, digest, locate_candidate
from gateway.hydradb import GraphTransport, ProposalReader, ProposalWriter, Publication

TEXT = ('Planning note, PLANT-A. Retained lot RET-731 may be added to batch MIX-842. '
        'Batch MIX-842 may supply pack lot PACK-953. '
        'Pack lot PACK-953 may be repacked as lot CASE-164. '
        'These are proposals only; no completed transfer or consumption records are available.')


async def run(args):
    cfg = dotenv_values('.env')
    transport = GraphTransport(cfg['HYDRA_DB_API_KEY'], 'gate0probe')
    try:
        if args.read_publication:
            publication = Publication(**json.loads(Path(args.read_publication).read_text()))
            result = await ProposalReader(transport).read(publication, page_size=1)
            Path(args.read_output).write_text(json.dumps(result, indent=2) + '\n')
            return
        demo = args.demo
        text = ('Planning note, PLANT-A. Retained lot INT-1000 may be added to batch INT-2000 at PLANT-B. '
                'Batch INT-2000 may supply lot INT-2002. '
                'Lot INT-2002 may be repacked as lot CASE-DEMO. '
                'These are proposals only; no completed transfer or consumption records for these links are available.') if demo else TEXT
        doc = SourceDocument(source_id='NOTE-DEMO-001' if demo else 'NOTE-GRAPH-731', source_version='1', text=text,
                             effective_at='2026-09-11T00:00:00Z',
                             received_at=datetime.now(timezone.utc).isoformat())
        if args.captured_extraction:
            extraction = json.loads(Path(args.captured_extraction).read_text())
            if extraction['text'] != doc.text or extraction['status'] != 'DATASET_PROCESSING_COMPLETED':
                raise ValueError('Captured sponsor result does not match this completed source ingestion')
        else:
            cognee = CogneeExtractor(cfg['COGNEE_SERVICE_URL'], cfg['COGNEE_API_KEY'])
            try:
                extraction = await cognee.extract(doc)
            finally:
                await cognee.close()
        candidates = parse_extraction(extraction['search'], extraction['add']['dataset_id'])
        claims, rejected, bindings = [], [], []
        for candidate in candidates.candidates:
            try:
                located, repaired = locate_candidate(candidate, doc)
                claims.append(bind_candidate(located, doc, digest(extraction)))
                bindings.append({'input_lot': candidate.input_lot, 'output_lot': candidate.output_lot,
                                 'generated_quote_replaced': repaired})
            except ValueError as error:
                rejected.append({'candidate': candidate.model_dump(), 'reason': str(error)})
        if rejected or not claims:
            raise ValueError('Extraction yielded rejected or no source-bound candidates; no graph publication')
        publication, write_receipt = await ProposalWriter(transport).publish(claims)
        root = Path('probes/results')
        root.mkdir(exist_ok=True)
        publication_path = root / 'graph_publication.json'
        publication_path.write_text(json.dumps(asdict(publication), indent=2) + '\n')
        reader_path = root / 'graph_reader.json'
        # This reader is a privileged integration probe, not an isolated agent.
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'probes.graph_bridge', '--read-publication', str(publication_path),
            '--read-output', str(reader_path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await process.communicate()
        if process.returncode != 0:
            raise RuntimeError('Separate HydraDB reader failed; no completion claim')
        read = json.loads(reader_path.read_text())
        assert read['coverage']['delivery_complete'], 'Publication did not read back completely'
        for claim in read['claims']:
            ptr = claim['source'];loc = ptr['locator']
            assert ptr['received_at'] == doc.received_at
            assert ptr['content_sha256'] == doc.content_sha256
            assert doc.text[loc['start']:loc['end']] == claim['quote']
            assert claim['status'] == 'PROPOSED'
        paths = await ProposalReader(transport).candidate_descendants(publication, 'INT-1000' if demo else 'RET-731')
        expected = {'INT-2000', 'INT-2002', 'CASE-DEMO'} if demo else {'MIX-842', 'PACK-953', 'CASE-164'}
        expected_paths_found = {r['lot_id'] for r in paths['rows']} == expected
        partial = await ProposalReader(transport).read(publication, page_size=1, max_pages=1)
        assert not partial['coverage']['delivery_complete']
        report = {'source': doc.model_dump(), 'cognee': extraction, 'source_bindings': bindings,
                  'extraction_mode': 'captured_live_result' if args.captured_extraction else 'fresh_live',
                  'publication': asdict(publication), 'write_receipt': write_receipt,
                  'read': read, 'candidate_paths': paths, 'budget_limited_read': partial,
                  'expected_fixture_paths_found': expected_paths_found,
                  'gate_0': 'OPEN: completed-event validation, committed incident revision and remaining sponsor handoffs pending'}
        (root / 'graph_bridge.json').write_text(json.dumps(report, indent=2) + '\n')
        assert expected_paths_found, 'Cognee extraction or graph traversal omitted fixture links; receipt saved, no complete handoff claim'
        print(json.dumps({'claims': len(claims), 'generated_quotes_replaced': sum(b['generated_quote_replaced'] for b in bindings),
                          'reader_process_pages': len(read['receipts']), 'candidate_descendants': paths['rows'],
                          'report': str(root / 'graph_bridge.json'), 'gate_0': 'OPEN'}, indent=2))
    finally:
        await transport.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--captured-extraction')
    parser.add_argument('--demo', action='store_true', help='Use lot IDs from the two demo facilities; links remain proposed')
    parser.add_argument('--read-publication')
    parser.add_argument('--read-output')
    asyncio.run(run(parser.parse_args()))
