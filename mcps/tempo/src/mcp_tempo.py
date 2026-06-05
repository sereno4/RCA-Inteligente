from fastapi import FastAPI
from pydantic import BaseModel
import httpx, os
from datetime import datetime, timedelta

app = FastAPI(title="MCP Tempo")
TEMPO_URL = os.getenv("TEMPO_URL",
  "http://tempo.rca-monitoring.svc.cluster.local:3200")

class TraceRequest(BaseModel):
    service: str
    lookback_minutes: int = 10
    limit: int = 20

@app.get("/health")
async def health():
    return {"status": "ok", "backend": TEMPO_URL}

@app.post("/search")
async def search_traces(req: TraceRequest):
    end   = int(datetime.utcnow().timestamp())
    start = end - req.lookback_minutes * 60
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(f"{TEMPO_URL}/api/search", params={
                "tags":  f"service.name={req.service}",
                "start": start,
                "end":   end,
                "limit": req.limit,
            })
            return r.json() if r.status_code == 200 else {"error": r.text[:200], "traces": []}
        except Exception as e:
            return {"error": str(e), "traces": []}

@app.post("/errors")
async def search_error_traces(req: TraceRequest):
    """Retorna só traces com erro — status != OK"""
    end   = int(datetime.utcnow().timestamp())
    start = end - req.lookback_minutes * 60
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            r = await client.get(f"{TEMPO_URL}/api/search", params={
                "tags":  f"service.name={req.service} status=error",
                "start": start,
                "end":   end,
                "limit": req.limit,
            })
            data = r.json() if r.status_code == 200 else {"traces": []}
            traces = data.get("traces", [])
            return {
                "service": req.service,
                "error_trace_count": len(traces),
                "traces": [{"traceID": t.get("traceID"), "rootName": t.get("rootName"),
                             "duration_ms": t.get("durationMs"), "startTime": t.get("startTimeUnixNano")}
                           for t in traces]
            }
        except Exception as e:
            return {"error": str(e), "traces": []}
