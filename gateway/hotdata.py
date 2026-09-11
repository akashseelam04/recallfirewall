"""Fixed Hotdata read operation. Only the gateway process runs the CLI."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal


class SponsorFailure(Exception):
    """Safe to expose; never include CLI stderr, environment, or raw responses."""


@dataclass(frozen=True)
class TaskBinding:
    task_id: str
    incident_id: str
    facility_id: str
    scope_revision: int
    input_epoch: int
    database_id: str
    catalog: str
    workspace_id: str
    source_manifest_sha256: str
    token_sha256: str
    expires_at: float
    role: str = 'facility_investigator'
    knowledge_revision: int = 0

    def __post_init__(self):
        for value in (self.task_id, self.incident_id, self.facility_id,
                      self.database_id, self.catalog, self.workspace_id, self.role):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
                raise ValueError("Invalid trusted task binding")
        for value in (self.source_manifest_sha256, self.token_sha256):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise ValueError("Expected SHA-256 digest")
        for value in (self.scope_revision, self.input_epoch, self.knowledge_revision):
            if type(value) is not int or value < 0:
                raise ValueError('Invalid task revision')
        if type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at):
            raise ValueError('Invalid task expiry')


def consumption_sql(binding: TaskBinding, ingredient: str) -> str:
    # CLI has no demonstrated parameter-binding interface. Strict identifier
    # grammar permits literal serialization here; no arbitrary SQL is accepted.
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{0,63}", ingredient):
        raise ValueError("Invalid ingredient identifier")
    return (
        "SELECT work_order_id, plant_id, output_lot, input_lot, ingredient_id, "
        "CAST(CAST(qty_kg AS DECIMAL(18,3)) AS VARCHAR) AS qty_kg, completed_at "
        f"FROM {binding.catalog}.public.lot_consumption "
        f"WHERE ingredient_id = '{ingredient}' "
        f"AND plant_id = '{binding.facility_id}' "
        "ORDER BY work_order_id, output_lot, input_lot"
    )


def decode_result(raw: str, binding: TaskBinding) -> dict:
    try:
        data = json.loads(raw, parse_float=Decimal)
        expected = ['work_order_id', 'plant_id', 'output_lot', 'input_lot',
                    'ingredient_id', 'qty_kg', 'completed_at']
        if data['columns'] != expected or not isinstance(data['rows'], list):
            raise ValueError()
        if type(data['truncated']) is not bool or type(data['row_count']) is not int:
            raise ValueError()
        if data['row_count'] != len(data['rows']):
            raise ValueError()
        total = data['total_row_count']
        if total is not None and (type(total) is not int or total < len(data['rows'])):
            raise ValueError()
        if not isinstance(data['query_run_id'], str) or not data['query_run_id']:
            raise ValueError()
        rows = []
        for values in data['rows']:
            if not isinstance(values, list) or len(values) != len(expected):
                raise ValueError()
            row = dict(zip(expected, values))
            if any(not isinstance(value, str) or not value for value in values):
                raise ValueError()
            if row['plant_id'] != binding.facility_id:
                raise ValueError()
            # Require decimal strings from the server, not already rounded floats.
            qty = row['qty_kg']
            if not isinstance(qty, str) or not re.fullmatch(r"\d{1,15}\.\d{3}", qty):
                raise ValueError()
            rows.append(row)
        delivered = not data['truncated'] and total == len(rows)
        return {
            'rows': rows,
            'query_run_id': data['query_run_id'],
            'result_sha256': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            'coverage': {
                'rows': len(rows), 'delivery_complete': delivered,
                'complete': False,
                'snapshot_or_revision': None,
                'source_manifest_sha256': binding.source_manifest_sha256,
                'incomplete_reason': 'immutable_vendor_snapshot_not_proven' if delivered
                                     else 'partial_or_unknown_delivery_and_unproven_snapshot',
            },
        }
    except (KeyError, TypeError, ValueError):
        raise SponsorFailure('Hotdata returned an invalid result contract') from None


class HotdataCLI:
    async def consumption(self, binding: TaskBinding, ingredient: str) -> dict:
        sql = consumption_sql(binding, ingredient)
        proc = await asyncio.create_subprocess_exec(
            'hotdata', 'query', '-w', binding.workspace_id, '-d', binding.database_id,
            sql, '-o', 'json', '--no-input',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except (TimeoutError, asyncio.CancelledError):
            proc.kill()
            await proc.communicate()
            raise SponsorFailure('Hotdata query timed out or was cancelled') from None
        # Exit 3 represents a successful but incomplete preview, never closure.
        if proc.returncode not in (0, 3):
            raise SponsorFailure(f'Hotdata query failed (exit {proc.returncode})')
        result = decode_result(stdout.decode(), binding)
        if any(row['ingredient_id'] != ingredient for row in result['rows']):
            raise SponsorFailure('Hotdata returned rows outside the requested ingredient')
        result['coverage']['scope'] = {
            'facility_id': binding.facility_id,
            'database_id': binding.database_id,
            'table': f'{binding.catalog}.public.lot_consumption',
            'ingredient_id': ingredient,
            'unit': 'kg',
        }
        result['sql'] = sql
        result['arguments'] = {'ingredient_id': ingredient}
        return result
