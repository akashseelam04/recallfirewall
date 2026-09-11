"""Create private task capabilities for the live Cloud-to-gateway demo."""
import hashlib
import json
import os
import secrets
import time
from dataclasses import asdict
from pathlib import Path

from gateway.hotdata import TaskBinding
from probes.hotdata_parallel import FACILITIES


def main():
    root = Path('.demo')
    root.mkdir(mode=0o700, exist_ok=True)
    run = secrets.token_hex(5)
    bindings, tasks = [], []
    for facility, target in FACILITIES.items():
        token = secrets.token_urlsafe(32)
        task_id = facility.lower() + '-' + run
        csv = Path('probes/data') / (facility.lower().replace('-', '_') + '_consumption.csv')
        binding = TaskBinding(task_id, 'demo-' + run, facility, 1, 1, target['database'],
                              target['catalog'], 'workjtyq38oc9fwowtl6s8g4i42jne',
                              hashlib.sha256(csv.read_bytes()).hexdigest(),
                              hashlib.sha256(token.encode()).hexdigest(), time.time() + 3600)
        bindings.append(asdict(binding))
        tasks.append({'task_id':task_id, 'facility_id':facility, 'token':token})
    config = {'tasks': tasks, 'bindings_file':str((root / ('bindings-' + run + '.json')).resolve()),
              'state_db':str((root / ('control-' + run + '.sqlite')).resolve())}
    for path, data in [(Path(config['bindings_file']),bindings),(root/'session.json',config)]:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f: json.dump(data,f)
    print('Private demo task configuration created; capabilities expire in one hour.')


if __name__ == '__main__': main()
