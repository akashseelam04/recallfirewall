"""Small transactional fictional shipment simulator. No real warehouse writes."""
import hashlib
import json
import time
import uuid

from gateway.store import ControlStore


class WarehouseConflict(Exception):
    pass


class Warehouse:
    def __init__(self, store: ControlStore):
        self.store = store
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS demo_shipments (
                shipment_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL,
                facility_id TEXT NOT NULL, lot_id TEXT NOT NULL, qty_kg TEXT NOT NULL,
                transport_state TEXT NOT NULL, version INTEGER NOT NULL, held INTEGER NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS demo_approvals (
                approval_id TEXT PRIMARY KEY, shipment_id TEXT NOT NULL,
                expected_version INTEGER NOT NULL, input_epoch INTEGER NOT NULL,
                expires_at REAL NOT NULL, actor TEXT NOT NULL, plan_hash TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS demo_actions (
                idempotency_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL, result_json TEXT NOT NULL)''')

    def seed(self, incident_id: str):
        """Trusted demo setup only; these quantities are original simulated stock."""
        with self.store.transaction() as db:
            for row in [('SHIP-DEMO-A','PLANT-A','INT-1000','25.100'),
                        ('SHIP-DEMO-B','PLANT-B','INT-2000','40.200')]:
                db.execute('INSERT OR IGNORE INTO demo_shipments VALUES (?,?,?,?,?,?,?,?)',
                           (row[0],incident_id,*row[1:],'STAGED',1,0))

    def shipments(self):
        with self.store.transaction() as db:
            return [dict(row) for row in db.execute('SELECT * FROM demo_shipments ORDER BY shipment_id')]

    def approve(self, shipment_id: str, expected_version: int, actor: str):
        """Called only by the authenticated operator API, never an agent tool."""
        with self.store.transaction() as db:
            row = db.execute('SELECT * FROM demo_shipments WHERE shipment_id=?',(shipment_id,)).fetchone()
            if row is None or row['version'] != expected_version or row['transport_state'] != 'STAGED' or row['held']:
                raise WarehouseConflict('Shipment is no longer eligible for this hold')
            incident = db.execute('SELECT * FROM incidents WHERE incident_id=?',(row['incident_id'],)).fetchone()
            if not incident or incident['input_state'] != 'READY':
                raise WarehouseConflict('Incident inputs are unpublished')
            plan = {'action':'HOLD_SHIPMENT','shipment_id':shipment_id,'version':expected_version,
                    'incident_id':row['incident_id'],'input_epoch':incident['input_epoch']}
            plan_hash = hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
            approval = {'approval_id':str(uuid.uuid4()),'shipment_id':shipment_id,'expected_version':expected_version,
                        'input_epoch':incident['input_epoch'],'expires_at':time.time()+300,'actor':actor,'plan_hash':plan_hash}
            db.execute('INSERT INTO demo_approvals VALUES (?,?,?,?,?,?,?)',tuple(approval.values()))
            return approval

    def hold(self, approval_id: str, idempotency_key: str):
        request_hash = hashlib.sha256(approval_id.encode()).hexdigest()
        with self.store.transaction() as db:
            old = db.execute('SELECT * FROM demo_actions WHERE idempotency_key=?',(idempotency_key,)).fetchone()
            if old:
                if old['request_hash'] != request_hash:
                    raise WarehouseConflict('Idempotency key belongs to a different action')
                return json.loads(old['result_json'])
            approval = db.execute('SELECT * FROM demo_approvals WHERE approval_id=?',(approval_id,)).fetchone()
            if approval is None or approval['expires_at'] <= time.time():
                raise WarehouseConflict('Missing or expired approval')
            row = db.execute('SELECT * FROM demo_shipments WHERE shipment_id=?',(approval['shipment_id'],)).fetchone()
            incident = db.execute('SELECT * FROM incidents WHERE incident_id=?',(row['incident_id'],)).fetchone()
            if incident['input_state'] != 'READY' or incident['input_epoch'] != approval['input_epoch']:
                raise WarehouseConflict('Approval is stale after an input update')
            if row['version'] != approval['expected_version'] or row['transport_state'] != 'STAGED':
                raise WarehouseConflict('Shipment state changed after approval')
            db.execute('UPDATE demo_shipments SET held=1,version=version+1 WHERE shipment_id=?',(row['shipment_id'],))
            result = {'status':'HELD','shipment_id':row['shipment_id'],'version':row['version']+1,
                      'approval_id':approval_id,'plan_hash':approval['plan_hash']}
            db.execute('INSERT INTO demo_actions VALUES (?,?,?)',(idempotency_key,request_hash,json.dumps(result)))
            return result

    def depart(self, shipment_id: str):
        with self.store.transaction() as db:
            row = db.execute('SELECT * FROM demo_shipments WHERE shipment_id=?',(shipment_id,)).fetchone()
            if row is None:
                raise WarehouseConflict('Unknown shipment')
            if row['held']:
                raise WarehouseConflict('DEPARTURE_BLOCKED: active protective hold')
            if row['transport_state'] != 'STAGED':
                raise WarehouseConflict('Shipment has already departed')
            db.execute("UPDATE demo_shipments SET transport_state='DEPARTED',version=version+1 WHERE shipment_id=?",(shipment_id,))
            return {'status':'DEPARTED','shipment_id':shipment_id,'version':row['version']+1}
