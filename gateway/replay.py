"""Read-only demo server. No credentials, sponsor calls, or mutation routes."""
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import uvicorn

ROOT = Path(__file__).resolve().parents[1] / 'demo'
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

@app.get('/')
async def index():
    return FileResponse(ROOT / 'index.html')

@app.get('/{asset}')
async def asset(asset: str):
    if asset not in {'index.html', 'presentation.html', 'style.css', 'app.js', 'data.js'}:
        raise HTTPException(404)
    return FileResponse(ROOT / asset)

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8791)
