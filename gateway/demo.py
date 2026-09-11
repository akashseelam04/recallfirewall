"""Start the current private demo gateway: python -m gateway.demo."""
import json
import os
from pathlib import Path
import uvicorn
from gateway.app import create_app
from gateway.hotdata import TaskBinding
from gateway.store import ControlStore

if __name__ == '__main__':
    config=json.loads(Path('.demo/session.json').read_text())
    bindings=[TaskBinding(**row) for row in json.loads(Path(config['bindings_file']).read_text())]
    app=create_app(bindings, store=ControlStore(config['state_db']))
    uvicorn.run(app, host='127.0.0.1',port=int(os.environ.get('GATEWAY_PORT','8790')),proxy_headers=False)
