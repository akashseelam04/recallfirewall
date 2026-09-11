"""Execute the captured Rote method on fresh parameters; retain live run receipts."""
import json
import subprocess
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    play = root / 'probes/plays/facility_query/main.ts'
    runs = []
    for facility, ingredient, expected_rows in [('PLANT-B', 'ING-041', 2),
                                                ('PLANT-A', 'ING-112', 1),
                                                ('PLANT-B', 'ING-999', 0)]:
        process = subprocess.run(['rote', 'play', 'run', str(play), 'root=' + str(root),
                                  'facility=' + facility, 'ingredient=' + ingredient, '--output', 'json'],
                                 cwd=tempfile.gettempdir(), capture_output=True, text=True, timeout=150)
        if process.returncode:
            raise RuntimeError('Rote replay failed; no successful replay claim')
        result = json.loads(process.stdout)
        finding = result['finding']
        assert result['status'] == 'succeeded' and result['receipt_verified']
        assert finding['facility_id'] == facility and finding['arguments']['ingredient_id'] == ingredient
        assert len(finding['rows']) == expected_rows
        assert finding['coverage']['complete'] is False, 'Do not convert empty results into complete coverage'
        runs.append(result)
        print(f"Rote {facility}/{ingredient}: {expected_rows} rows, receipt verified", flush=True)
    assert len({run['finding']['query_run_id'] for run in runs}) == len(runs)
    output = root / 'probes/results/rote_facility.json'
    output.write_text(json.dumps({'mode': 'live_parameterized_replay', 'runs': runs,
                                 'limitation': 'Existing vendor fixture databases; fresh task snapshots and full AC-13 are not proved'}, indent=2) + '\n')
    print('Saved probes/results/rote_facility.json')


if __name__ == '__main__':
    main()
