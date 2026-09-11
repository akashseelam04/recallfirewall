"""Run the available live sponsor chain and expose explicit blockers in the console.

Use --cloud only with an approved GATEWAY_PUBLIC_URL. Default Cloud mode runs
reviewed deterministic branching in RocketRide; --agent uses the LLM instead.
--connectivity-only checks transport and never claims branching is verified.
Human approval and simulator execution remain in the separate operator console.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cloud', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--connectivity-only', action='store_true')
    mode.add_argument('--agent', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / 'probes/results/demo_run.json'
    report = {'started_at': time.time(), 'status': 'RUNNING', 'synthetic': True,
              'stages': {}, 'finding_status': 'UNRESOLVED', 'approval': 'LOCAL_OPERATOR_REQUIRED'}

    def save():
        output.parent.mkdir(exist_ok=True)
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(output)

    def stage(name, command, artifact, timeout=240):
        report['stages'][name] = {'status': 'RUNNING', 'started_at': time.time()}
        save()
        print(name + ': running live calls', flush=True)
        try:
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=timeout)
            ok = result.returncode == 0
            # Raw third-party errors can contain credentials. Keep only the
            # redacted adapter-owned artifact, never arbitrary subprocess text.
            report['stages'][name].update(status='PASSED' if ok else 'FAILED',
                                         exit_code=result.returncode, artifact=artifact)
            if not ok:
                from dotenv import dotenv_values
                diagnostic = result.stderr[-4000:]
                for key, value in dotenv_values(root / '.env').items():
                    if value and any(word in key for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')):
                        diagnostic = diagnostic.replace(value, '<redacted>')
                report['stages'][name]['diagnostic'] = diagnostic
        except subprocess.TimeoutExpired:
            ok = False
            report['stages'][name].update(status='FAILED', reason='Stage exceeded its deadline')
        report['stages'][name]['ended_at'] = time.time()
        save()
        print(name + ': ' + report['stages'][name]['status'], flush=True)
        return ok

    save()
    graph_ok = stage('cognee_hydradb', [sys.executable, '-m', 'probes.graph_bridge', '--demo'],
                     'probes/results/graph_bridge.json')
    if graph_ok:
        graph = json.loads((root / 'probes/results/graph_bridge.json').read_text())
        report['evidence'] = {'source': graph['source'], 'claims': graph['read']['claims'],
                              'candidate_paths': graph['candidate_paths']['rows']}
    if args.cloud and os.environ.get('GATEWAY_PUBLIC_URL') and graph_ok:
        script = 'probe_gateway.mjs' if args.connectivity_only else 'run_facility.mjs' if args.agent else 'run_dispatch.mjs'
        command = ['/opt/homebrew/bin/node', 'orchestrator/' + script, 'ING-041']
        if args.agent:
            command.append('probes/results/graph_bridge.json')
        artifact = 'probes/results/' + ('rocketride_gateway.json' if args.connectivity_only else
                                        'rocketride_facility.json' if args.agent else 'rocketride_dispatch.json')
        cloud_ok = stage('rocketride', command, artifact)
        report['stages']['rocketride']['mode'] = 'CONNECTIVITY_ONLY' if args.connectivity_only else 'LLM_AGENT' if args.agent else 'CLOUD_FIXED_PROCEDURE'
        if cloud_ok and not args.connectivity_only and not args.agent:
            dispatch = json.loads((root / artifact).read_text())
            report['cloud_finding'] = dispatch['response']['result']
            report['finding_status'] = report['cloud_finding']['status']
    else:
        report['stages']['rocketride'] = {'status': 'BLOCKED',
            'reason': 'Requires successful graph handoff and --cloud with an approved GATEWAY_PUBLIC_URL; agent mode also needs model credits'}
    # Independent replay verification is useful even if Cloud is blocked. It is
    # explicitly not represented as a fallback investigator or complete chain.
    rote_ok = stage('rote_hotdata', [sys.executable, '-m', 'probes.replay_facility'],
                    'probes/results/rote_facility.json')
    if rote_ok:
        replay = json.loads((root / 'probes/results/rote_facility.json').read_text())
        report['replays'] = [{'run_id': run['run_id'], 'finding': run['finding'],
                              'receipt_verified': run['receipt_verified']} for run in replay['runs']]
    report['status'] = 'COMPONENTS_VERIFIED' if all(s['status'] == 'PASSED' for s in report['stages'].values()) else 'BLOCKED'
    report['limitation'] = 'Component success is not full acceptance: graph links remain proposals; human approval and hold verification are separate; existing vendor fixture databases are reused.'
    report['ended_at'] = time.time()
    save()
    print('Report: probes/results/demo_run.json; operator console: http://127.0.0.1:8791', flush=True)
    return 0 if report['status'] == 'COMPONENTS_VERIFIED' else 1


if __name__ == '__main__':
    sys.exit(main())
