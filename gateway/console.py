"""Local operator UI. Separate from the externally callable agent gateway."""
import json
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict
import uvicorn

from gateway.hotdata import TaskBinding
from gateway.store import ControlStore
from gateway.warehouse import Warehouse, WarehouseConflict


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    shipment_id: str
    expected_version: int


class HoldInput(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    approval_id: str
    idempotency_key: str


class DepartureInput(BaseModel):
    model_config = ConfigDict(extra='forbid',strict=True)
    shipment_id: str


def create_console(warehouse: Warehouse):
    app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    operator_key = secrets.token_urlsafe(32)

    @app.middleware('http')
    async def local_operator(request: Request, call_next):
        if request.headers.get('host') not in ('127.0.0.1:8791','localhost:8791'):
            return JSONResponse({'detail':'Local operator console only'},status_code=403)
        if request.url.path.startswith('/api/') and not secrets.compare_digest(request.headers.get('x-operator-key',''),operator_key):
            return JSONResponse({'detail':'Operator authentication required'},status_code=401)
        return await call_next(request)

    @app.exception_handler(WarehouseConflict)
    async def conflict(request, error):
        return JSONResponse({'detail':str(error)},status_code=409)

    @app.get('/',response_class=HTMLResponse)
    async def page():
        return Path('gateway/console.html').read_text().replace('__OPERATOR_KEY__',operator_key)

    @app.get('/api/shipments')
    async def shipments(): return warehouse.shipments()

    @app.get('/api/investigation')
    async def investigation():
        path = Path(__file__).resolve().parents[1] / 'probes/results/demo_run.json'
        if not path.exists():
            return {'status': 'NOT_RUN', 'stages': {}}
        return json.loads(path.read_text())

    @app.post('/api/approvals')
    async def approve(body: ApprovalInput):
        return warehouse.approve(body.shipment_id,body.expected_version,'local-operator')

    @app.post('/api/holds')
    async def hold(body: HoldInput): return warehouse.hold(body.approval_id,body.idempotency_key)

    @app.post('/api/departures')
    async def depart(body: DepartureInput): return warehouse.depart(body.shipment_id)

    return app


if __name__ == '__main__':
    config=json.loads(Path('.demo/session.json').read_text())
    store=ControlStore(config['state_db'])
    bindings=[TaskBinding(**row) for row in json.loads(Path(config['bindings_file']).read_text())]
    for binding in bindings:store.register(binding)
    warehouse=Warehouse(store);warehouse.seed(bindings[0].incident_id)
    uvicorn.run(create_console(warehouse),host='127.0.0.1',port=8791,proxy_headers=False)
