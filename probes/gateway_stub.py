"""Gate 0 probe: is a local tool gateway reachable from the public internet?

SPEC.md 6.1 makes Cloud-to-gateway reachability and credentials a pre-build gate.
RocketRide Cloud runs the pipelines but the tool gateway runs here, so the Cloud
has to be able to call in. This stub proves the network path and the auth check
without depending on any sponsor credential.

Run:  uvicorn probes.gateway_stub:app --port 8787
"""

import os

from fastapi import FastAPI, Header, HTTPException

GATEWAY_KEY = os.environ.get("GATEWAY_KEY", "")

app = FastAPI(title="Recall Firewall gateway stub")


@app.get("/health")
async def health():
    """Unauthenticated liveness probe."""
    return {"status": "ok", "service": "gateway-stub"}


@app.post("/tools/echo")
async def echo(payload: dict, x_gateway_key: str = Header(default="")):
    """Authenticated tool call, shaped like the real gateway's tool endpoints."""
    if not GATEWAY_KEY or x_gateway_key != GATEWAY_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"received": payload, "authenticated": True}
