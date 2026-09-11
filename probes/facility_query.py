"""Read-only Rote process adapter. Uses task capabilities, never vendor credentials."""
import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['consumption', 'receipt'])
    parser.add_argument('--facility', required=True, choices=['PLANT-A', 'PLANT-B'])
    parser.add_argument('--ingredient', default='ING-041')
    parser.add_argument('--receipt-id')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    session = json.loads((root / '.demo/session.json').read_text())
    task = next(t for t in session['tasks'] if t['facility_id'] == args.facility)
    base = 'http://127.0.0.1:8790/v1/tasks/' + task['task_id']
    headers = {'Authorization': 'Bearer ' + task['token'], 'Content-Type': 'application/json'}
    if args.operation == 'consumption':
        request = Request(base + '/consumption', data=json.dumps({'ingredient_id': args.ingredient}).encode(), headers=headers)
    else:
        import uuid
        receipt_id = str(uuid.UUID(args.receipt_id or ''))
        request = Request(base + '/receipts/' + receipt_id, headers=headers)
    try:
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f'Gateway HTTP {error.code}; no fallback') from None
    except URLError:
        raise RuntimeError('Gateway unavailable; start gateway.demo') from None
    if (result.get('facility_id') != args.facility or result.get('task_id') != task['task_id']
            or not result.get('query_run_id') or not result.get('receipt_id')
            or result.get('current_status', result.get('admission_status')) != 'CURRENT'):
        raise RuntimeError('Gateway returned stale or invalid provenance')
    if args.operation == 'consumption' and result.get('arguments', {}).get('ingredient_id') != args.ingredient:
        raise RuntimeError('Gateway returned the wrong ingredient')
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError, StopIteration) as error:
        print('Facility query failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
