import asyncio
import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any, List

app = FastAPI(title="AOF MCP Server")

# Endpoints dos workers internos
WORKERS = {
    "prometheus": "http://mcp-prometheus.rca-system.svc.cluster.local:8000",
    "loki": "http://mcp-loki.rca-system.svc.cluster.local:8000",
    "tempo": "http://mcp-tempo.rca-system.svc.cluster.local:8000",
    "qdrant": "http://mcp-qdrant.rca-system.svc.cluster.local:8000",
}

class EvidenceRequest(BaseModel):
    service: str
    alert_time: str
    lookback_minutes: int = 10

class EvidenceResponse(BaseModel):
    service: str
    metrics: Dict[str, Any]
    logs: Dict[str, Any]
    traces: Dict[str, Any]
    rag_matches: List[Dict]

@app.post("/collect", response_model=EvidenceResponse)
async def collect_evidence(req: EvidenceRequest):
    """Dispatch 4 workers in parallel"""
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [
            _fetch_worker(client, "prometheus", "/query", {
                "service": req.service,
                "lookback_minutes": req.lookback_minutes
            }),
            _fetch_worker(client, "loki", "/query", {
                "service": req.service,
                "lookback_minutes": req.lookback_minutes
            }),
            _fetch_worker(client, "tempo", "/query", {
                "service": req.service
            }),
            _fetch_worker(client, "qdrant", "/search", {
                "service": req.service,
                "description": f"Incident in {req.service}"
            }),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    metrics = results[0] if not isinstance(results[0], Exception) else {"error": str(results[0])}
    logs = results[1] if not isinstance(results[1], Exception) else {"error": str(results[1])}
    traces = results[2] if not isinstance(results[2], Exception) else {"error": str(results[2])}
    rag = results[3] if not isinstance(results[3], Exception) else {"error": str(results[3])}
    
    return EvidenceResponse(
        service=req.service,
        metrics=metrics,
        logs=logs,
        traces=traces,
        rag_matches=rag.get("matches", []) if isinstance(rag, dict) else []
    )

async def _fetch_worker(client: httpx.AsyncClient, worker: str, path: str, payload: dict):
    url = f"{WORKERS[worker]}{path}"
    r = await client.post(url, json=payload)
    return r.json() if r.status_code == 200 else {"error": r.text}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
