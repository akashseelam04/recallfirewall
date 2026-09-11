"""Freeze executed sponsor receipts into a credential-free, offline demo bundle."""
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    results = root / 'probes/results'
    def read(name):
        return json.loads((results / name).read_text())
    graph = read('graph_bridge.json')
    dispatch = read('rocketride_dispatch_positive.json')
    negative = read('rocketride_dispatch.json')
    replay = read('rote_facility.json')
    hold = read('warehouse_http.json')
    npm, python = read('snyk_npm.json'), read('snyk_python.json')
    assert graph['expected_fixture_paths_found'] and graph['read']['coverage']['delivery_complete']
    assert dispatch['success'] and dispatch['response']['result']['branch'] == 'QUERY_PLANT_B'
    assert negative['success'] and negative['response']['result']['branch'] == 'REQUEST_SOURCE_COVERAGE'
    assert hold['read_back']['held'] == 1 and hold['departure_http'] == 409
    data = {
        'built_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'Recorded live executions, fictional scenario; no live calls from this UI',
        'source': graph['source'],
        'claims': graph['read']['claims'],
        'cognee_run': graph['cognee']['add']['pipeline_run_id'],
        'hydra_receipt': graph['write_receipt']['native_meta']['request_id'],
        'hydra_pages': len(graph['read']['receipts']),
        'cloud': dispatch['response']['result'],
        'cloud_started': dispatch['started_at'],
        'negative': negative['response']['result'],
        'replays': [{'run_id': r['run_id'], 'finding': r['finding'],
                     'receipt_verified': r['receipt_verified']} for r in replay['runs']],
        'hold': hold,
        'security': {
            'npm': {'ok': npm['ok'], 'dependencies': npm['dependencyCount'], 'issues': len(npm['vulnerabilities'])},
            'python': {'ok': python['ok'], 'dependencies': python['dependencyCount'], 'issues': len(python['vulnerabilities'])},
            'code': {'status': 'NOT_ENABLED', 'reason': 'The organization has not enabled Snyk Code; no clean source-scan claim.'},
        },
        'model_connected': read('rocketride_model.json')['connected'],
        'limits': ['Source text establishes a proposed relationship, not a completed transfer.',
                   'Facility records are scoped reads from existing fixture databases, not full incident coverage.',
                   'The protective hold is a local simulator result, not a real warehouse action.',
                   'This replay combines saved executions. It makes no latency or cost comparison.'],
    }
    summary_path = results / 'security_summary.json'
    if summary_path.exists():
        checks = json.loads(summary_path.read_text())['checks']
        code_checks = [checks[name] for name in ('code', 'ui_code') if name in checks]
        if len(code_checks) == 2 and all(check['exit_code'] == 0 for check in code_checks):
            data['security']['code'] = {'status': 'PASSED', 'reason': 'Snyk Code scanned the gateway and read-only UI. Both scans completed with zero reported findings; no issues were ignored.'}
        elif code_checks:
            data['security']['code'] = {'status': 'FINDINGS', 'reason': 'The latest source scans require attention. See the recorded security summary for the exact outcomes.'}
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    # Defense against accidentally including capabilities in a presentation.
    from dotenv import dotenv_values
    for name, value in dotenv_values(root / '.env').items():
        if value and len(value) >= 8 and any(word in name for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
            assert value not in text, 'Secret present in replay data'
    session = json.loads((root / '.demo/session.json').read_text())
    assert all(task['token'] not in text for task in session['tasks'])
    output = root / 'demo/data.js'
    output.parent.mkdir(exist_ok=True)
    output.write_text('window.REPLAY = ' + text.replace('<', '\\u003c') + ';\n')
    print('Built demo/data.js from executed receipts; no credentials included.')


if __name__ == '__main__':
    main()
