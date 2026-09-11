"""Run Snyk checks with explicit exit status and fresh JSON evidence, no ignores."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from dotenv import dotenv_values


def main():
    root = Path(__file__).resolve().parents[1]
    values = dotenv_values(root / '.env')
    env = {**os.environ, 'SNYK_TOKEN': values['SNYK_TOKEN']}
    definitions = [
        ('npm', root / 'orchestrator', ['test', '--file=package.json']),
        ('python', root / 'gateway', ['test', '--file=requirements.txt', '--package-manager=pip',
                                    '--command=' + str(root / '.venv/bin/python')]),
        ('code', root, ['code', 'test', 'gateway']),
        ('ui_code', root, ['code', 'test', 'demo']),
    ]
    summary = {'started_at': time.time(), 'checks': {}}
    for name, cwd, command in definitions:
        print('Snyk ' + name + ': scanning', flush=True)
        result = subprocess.run(['/opt/homebrew/bin/snyk', *command, '--json'], cwd=cwd,
                                env=env, capture_output=True, text=True, timeout=200)
        stdout = result.stdout
        for key, secret in values.items():
            if secret and any(word in key for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
                stdout = stdout.replace(secret, '<redacted>')
        try:
            evidence = json.loads(stdout)
        except ValueError:
            evidence = {'unparsed_output': stdout[-2500:], 'exit_code': result.returncode}
        path = root / 'probes/results' / ('snyk_' + name + '.json')
        # Always replace the old artifact, even when the scanner returns no issues.
        path.write_text(json.dumps(evidence, indent=2) + '\n')
        summary['checks'][name] = {'exit_code': result.returncode,
                                  'status': 'PASSED' if result.returncode == 0 else 'FINDINGS' if result.returncode == 1 else 'FAILED',
                                  'artifact': str(path.relative_to(root))}
        print('Snyk ' + name + ': ' + summary['checks'][name]['status'], flush=True)
    summary['ended_at'] = time.time()
    summary['status'] = 'PASSED' if all(v['exit_code'] == 0 for v in summary['checks'].values()) else 'REQUIRES_ATTENTION'
    (root / 'probes/results/security_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return 0 if summary['status'] == 'PASSED' else 1


if __name__ == '__main__':
    sys.exit(main())
