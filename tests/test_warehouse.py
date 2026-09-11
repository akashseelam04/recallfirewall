"""Local simulator tests; no mocked sponsor calls and no real warehouse actions."""
import unittest
from fastapi.testclient import TestClient
from gateway.console import create_console
from gateway.store import ControlStore
from gateway.warehouse import Warehouse,WarehouseConflict
from test_gateway import binding


class WarehouseTests(unittest.TestCase):
    def setUp(self):
        self.store=ControlStore();self.addCleanup(self.store.close)
        self.store.register(binding());self.warehouse=Warehouse(self.store)
        self.warehouse.seed('incident-test')

    def test_approved_hold_persists_and_prevents_departure(self):
        approval=self.warehouse.approve('SHIP-DEMO-A',1,'unit-test-operator')
        held=self.warehouse.hold(approval['approval_id'],'action-1')
        self.assertEqual(held['status'],'HELD')
        self.assertEqual(self.warehouse.shipments()[0]['held'],1)
        self.assertEqual(self.warehouse.hold(approval['approval_id'],'action-1'),held)
        with self.assertRaises(WarehouseConflict):self.warehouse.depart('SHIP-DEMO-A')

    def test_departure_between_approval_and_hold_is_rejected(self):
        approval=self.warehouse.approve('SHIP-DEMO-A',1,'unit-test-operator')
        self.warehouse.depart('SHIP-DEMO-A')
        with self.assertRaises(WarehouseConflict):self.warehouse.hold(approval['approval_id'],'action-1')
        self.assertEqual(self.warehouse.shipments()[0]['held'],0)

    def test_input_update_blocks_pending_hold_but_keeps_completed_hold(self):
        a=self.warehouse.approve('SHIP-DEMO-A',1,'unit-test-operator')
        b=self.warehouse.approve('SHIP-DEMO-B',1,'unit-test-operator')
        result=self.warehouse.hold(a['approval_id'],'action-a')
        self.store.invalidate_inputs('incident-test',1)
        with self.assertRaises(WarehouseConflict):self.warehouse.hold(b['approval_id'],'action-b')
        self.assertEqual(self.warehouse.hold(a['approval_id'],'action-a'),result)
        self.assertEqual(self.warehouse.shipments()[0]['held'],1)

    def test_missing_expired_and_changed_approval_rejected(self):
        with self.assertRaises(WarehouseConflict):self.warehouse.hold('missing','action')
        a=self.warehouse.approve('SHIP-DEMO-A',1,'unit-test-operator')
        with self.store.transaction() as db:db.execute('UPDATE demo_approvals SET expires_at=0')
        with self.assertRaises(WarehouseConflict):self.warehouse.hold(a['approval_id'],'action')

    def test_operator_endpoint_does_not_accept_agent_token(self):
        client=TestClient(create_console(self.warehouse),base_url='http://127.0.0.1:8791')
        self.assertEqual(client.post('/api/approvals',headers={'Authorization':'Bearer unit-test-a'},json={'shipment_id':'SHIP-DEMO-A','expected_version':1}).status_code,401)
        self.assertEqual(client.get('/').status_code,200)

    def test_foreign_host_is_rejected_without_server_error(self):
        client=TestClient(create_console(self.warehouse),base_url='http://foreign.example')
        self.assertEqual(client.get('/').status_code,403)
