"""Fixed procedure executed by RocketRide Cloud's Python tool, not locally.

The trusted runner injects cfg: ingredient, scoped task capabilities, gateway
origin and source-bound graph proposals. No vendor credentials or arbitrary SQL.
"""
import json
import re
import urllib.request


def call(task, operation, body=None):
    endpoint = cfg['gateway'] + '/v1/tasks/' + task['task_id'] + '/' + operation
    request = urllib.request.Request(endpoint,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + task['token'], 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=40) as response:
        result = json.load(response)
    if result['facility_id'] != task['facility_id'] or result['task_id'] != task['task_id']:
        raise ValueError('Gateway scope mismatch')
    if result.get('current_status', result.get('admission_status')) != 'CURRENT':
        raise ValueError('Stale facility result')
    return result


def investigate(task):
    finding = call(task, 'consumption', {'ingredient_id': cfg['ingredient_id']})
    if finding['arguments']['ingredient_id'] != cfg['ingredient_id']:
        raise ValueError('Wrong ingredient returned')
    receipt_id = finding['receipt_id']
    if not re.fullmatch(r'[0-9a-f-]{36}', receipt_id):
        raise ValueError('Invalid receipt identifier')
    receipt = call(task, 'receipts/' + receipt_id)
    if receipt['query_run_id'] != finding['query_run_id'] or receipt['result_sha256'] != finding['result_sha256']:
        raise ValueError('Receipt did not match the fresh finding')
    return finding


plant_a = next(t for t in cfg['tasks'] if t['facility_id'] == 'PLANT-A')
plant_b = next(t for t in cfg['tasks'] if t['facility_id'] == 'PLANT-B')
first = investigate(plant_a)
visible_lots = {row['output_lot'] for row in first['rows']}
proposals = [claim for claim in cfg['claims']
             if claim['status'] == 'PROPOSED' and claim['input_lot'] in visible_lots]
findings = [first]
if proposals:
    findings.append(investigate(plant_b))
result = {
    'status': 'REVIEW_REQUIRED' if proposals else 'UNRESOLVED',
    'execution': 'ROCKETRIDE_CLOUD_FIXED_PROCEDURE',
    'branch': 'QUERY_PLANT_B' if proposals else 'REQUEST_SOURCE_COVERAGE',
    'queried_facilities': [f['facility_id'] for f in findings],
    'matched_proposed_claim_ids': [claim['claim_id'] for claim in proposals],
    'findings': findings,
    'next_action': 'REQUEST_COMPLETION_RECORDS' if proposals else 'REQUEST_SOURCE_COVERAGE',
    'gaps': ['Proposed links do not establish completed material transfers.',
             'Existing vendor snapshots do not establish complete incident coverage.'],
}
