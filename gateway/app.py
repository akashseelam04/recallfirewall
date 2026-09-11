"""Task-scoped HTTP boundary. No sponsor proxy, SQL, shell, or task-admin route.

Trusted startup supplies bindings. Workers receive only their expiring bearer
capability and gateway URL. Deploy workers separately without the gateway's
home directory, session file, environment, or filesystem tools.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gateway.hotdata import HotdataCLI, SponsorFailure, TaskBinding
from gateway.store import ControlStore, StaleTask


class ConsumptionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    ingredient_id: str = Field(pattern=r'^[A-Z0-9][A-Z0-9-]{0,63}$')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def create_app(bindings: list[TaskBinding], adapter=None, *, store: ControlStore | None = None) -> FastAPI:
    if len({b.task_id for b in bindings}) != len(bindings) or len({b.token_sha256 for b in bindings}) != len(bindings):
        raise ValueError('Task IDs and capabilities must be unique')
    registry = store if store is not None else ControlStore()
    for binding in bindings:
        registry.register(binding)
    sponsor = adapter if adapter is not None else HotdataCLI()
    app = FastAPI(title='Recall Firewall task gateway', docs_url=None,
                  redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def transport_boundary(request: Request, call_next):
        # Proxy/transport headers carry no authority and are never forwarded to
        # sponsors. Reject scope selectors, rather than breaking Cloudflare/MCP
        # by requiring an exhaustive list of incidental transport headers.
        names = [key.decode().lower() for key, _ in request.scope['headers']]
        scope_headers = {'database', 'database-id', 'x-database-id', 'hotdata-database-id',
                         'x-hotdata-database-id', 'x-workspace-id', 'x-task-id',
                         'workspace-id', 'task-id', 'x-query-run-id', 'x-result-id'}
        if request.url.query or any(name.replace('_', '-') in scope_headers for name in names):
            return JSONResponse({'detail': 'Unsupported request context'}, status_code=400)
        if names.count('authorization') != 1:
            return JSONResponse({'detail': 'Unauthorized'}, status_code=401)
        if names.count('content-type') > 1:
            return JSONResponse({'detail': 'Ambiguous content type'}, status_code=400)
        return await call_next(request)

    def authorize(request: Request, task_id: str) -> TaskBinding:
        binding = registry.credential_binding(task_id)
        auth = request.headers.get('authorization', '')
        digest = hashlib.sha256(auth.removeprefix('Bearer ').encode()).hexdigest()
        if (binding is None or not auth.startswith('Bearer ')
                or not hmac.compare_digest(digest, binding.token_sha256)
                or binding.expires_at <= time.time()):
            raise HTTPException(401, 'Unauthorized')
        return binding

    @app.post('/v1/tasks/{task_id}/consumption')
    async def consumption(task_id: str, request: Request):
        binding = authorize(request, task_id)
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            raise HTTPException(415, 'Expected application/json')
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 4096:
                raise HTTPException(413, 'Request too large')
        try:
            payload = ConsumptionRequest.model_validate(json.loads(body, object_pairs_hook=unique_object))
        except (ValueError, ValidationError):
            # Pydantic's default error response echoes the rejected input.
            raise HTTPException(422, 'Invalid operation arguments') from None
        return await run_consumption(binding, payload, request)

    async def run_consumption(binding: TaskBinding, payload: ConsumptionRequest, request: Request):
        task_id = binding.task_id
        try:
            registry.require_current(binding)
        except StaleTask:
            raise HTTPException(409, 'Task input basis is stale or unpublished') from None
        started = time.time()
        try:
            result = await sponsor.consumption(binding, payload.ingredient_id)
        except (SponsorFailure, OSError):
            raise HTTPException(502, 'Hotdata operation failed; no finding produced') from None
        receipt_id = str(uuid.uuid4())
        result.update({
            'receipt_id': receipt_id, 'task_id': task_id,
            'incident_id': binding.incident_id, 'facility_id': binding.facility_id,
            'scope_revision': binding.scope_revision, 'input_epoch': binding.input_epoch,
            'knowledge_revision': binding.knowledge_revision, 'role': binding.role,
            'database_id': binding.database_id, 'workspace_id': binding.workspace_id,
            'operation': 'consumption_records_v1', 'status': 'INCOMPLETE',
            'client_started_at': started, 'client_ended_at': time.time(),
        })
        saved = registry.save_receipt(binding, result)
        # Persist late results, but revoked/expired credentials must not receive
        # the response merely because they were valid before the sponsor call.
        authorize(request, task_id)
        return saved

    @app.post('/v1/tasks/{task_id}/mcp')
    async def mcp(task_id: str, request: Request):
        """Minimal stateless MCP JSON transport for the two fixed read tools."""
        binding = authorize(request, task_id)
        raw = await request.body()
        if len(raw) > 16384:
            raise HTTPException(413, 'Request too large')
        try:
            message = json.loads(raw, object_pairs_hook=unique_object)
            if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
                raise ValueError()
            method = message['method']
            params = message.get('params', {})
            if not isinstance(params, dict) or not isinstance(method, str):
                raise ValueError()
        except (ValueError, KeyError):
            return JSONResponse({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Invalid request'}}, status_code=400)
        request_id = message.get('id')
        if method.startswith('notifications/'):
            return Response(status_code=202)
        if method == 'initialize':
            result = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {}},
                      'serverInfo': {'name':'recall-firewall', 'version':'0.1.0'}}
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': [
                {'name':'consumption', 'description':'Read ingredient consumption records from your assigned facility through Hotdata. Coverage may be incomplete.',
                 'inputSchema':ConsumptionRequest.model_json_schema()},
                {'name':'get_receipt', 'description':'Read back a gateway receipt belonging to your assigned task.',
                 'inputSchema':{'type':'object','properties':{'receipt_id':{'type':'string'}},'required':['receipt_id'],'additionalProperties':False}}
            ]}
        elif method == 'tools/call':
            try:
                arguments = params.get('arguments', {})
                if params.get('name') == 'consumption':
                    payload = ConsumptionRequest.model_validate(arguments)
                    data = await run_consumption(binding, payload, request)
                elif params.get('name') == 'get_receipt' and isinstance(arguments, dict) and set(arguments) == {'receipt_id'} and isinstance(arguments['receipt_id'], str):
                    data = registry.receipt(binding, arguments['receipt_id'])
                    if data is None:
                        raise HTTPException(404, 'Receipt not found')
                else:
                    raise ValueError()
                result = {'content':[{'type':'text','text':json.dumps(data)}], 'isError':False}
            except (ValueError, HTTPException):
                result = {'content':[{'type':'text','text':'Tool failed: invalid arguments, stale task, missing receipt or sponsor failure.'}], 'isError':True}
        else:
            return {'jsonrpc':'2.0','id':request_id,'error':{'code':-32601,'message':'Method not found'}}
        return {'jsonrpc':'2.0','id':request_id,'result':result}

    @app.get('/v1/tasks/{task_id}/receipts/{receipt_id}')
    async def receipt(task_id: str, receipt_id: str, request: Request):
        binding = authorize(request, task_id)
        result = registry.receipt(binding, receipt_id)
        if result is None:
            raise HTTPException(404, 'Receipt not found')
        return result

    return app


def from_config() -> FastAPI:
    """uvicorn gateway.app:from_config --factory (trusted local startup only)."""
    root = Path(__file__).resolve().parents[1] / '.demo'
    config = json.loads((root / 'session.json').read_text())
    bindings_path = Path(config['bindings_file']).resolve()
    state_path = Path(config['state_db']).resolve()
    if not all(path.is_relative_to(root.resolve()) for path in (bindings_path, state_path)):
        raise ValueError('Gateway configuration files must stay inside the private demo directory')
    store = ControlStore(str(state_path))
    return create_app([TaskBinding(**item) for item in json.loads(bindings_path.read_text())], store=store)
