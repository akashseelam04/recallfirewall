"""MOCK sponsor unit tests for the minimal MCP transport."""
import json
import unittest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from gateway.app import create_app
from test_gateway import binding


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.sponsor=AsyncMock()
        self.sponsor.consumption.return_value={'rows':[], 'coverage':{'complete':False}}
        self.client=TestClient(create_app([binding()],self.sponsor))
        self.headers={'Authorization':'Bearer unit-test-a','CF-Ray':'MOCK-ray',
                      'X-Forwarded-Proto':'https','MCP-Protocol-Version':'2025-03-26'}
        self.url='/v1/tasks/task-a/mcp'

    def call(self, method, params=None):
        return self.client.post(self.url,headers=self.headers,json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})

    def test_handshake_discovery_and_call_use_bound_task(self):
        self.assertEqual(self.call('initialize').json()['result']['protocolVersion'],'2025-03-26')
        names={t['name'] for t in self.call('tools/list').json()['result']['tools']}
        self.assertEqual(names,{'consumption','get_receipt'})
        result=self.call('tools/call',{'name':'consumption','arguments':{'ingredient_id':'ING-041'}}).json()['result']
        self.assertFalse(result['isError'])
        self.assertEqual(self.sponsor.consumption.call_args.args[0].database_id,'database-a')
        data=json.loads(result['content'][0]['text'])
        result=self.call('tools/call',{'name':'get_receipt','arguments':{'receipt_id':data['receipt_id']}}).json()['result']
        self.assertFalse(result['isError'])

    def test_mcp_scope_override_is_rejected_without_call(self):
        for args in [{'ingredient_id':'ING-041','database_id':'database-b'},
                     {'ingredient_id':'ING-041','task_id':'task-b'}]:
            result=self.call('tools/call',{'name':'consumption','arguments':args}).json()['result']
            self.assertTrue(result['isError'])
        self.sponsor.consumption.assert_not_awaited()

    def test_bad_auth_and_malformed_method(self):
        self.assertEqual(self.client.post(self.url,json={}).status_code,401)
        self.assertEqual(self.call([]).status_code,400)
        self.assertEqual(self.call('not-a-method').json()['error']['code'],-32601)
