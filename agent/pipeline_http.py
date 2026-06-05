from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from pipeline import RCAPipeline, Alert
from llm_chain import run_llm_chain

app = FastAPI(title="RCA Agent", version="2.0")
pipeline = RCAPipeline()

class AlertRequest(BaseModel):
    service: str
    severity: str = "critical"
    description: str
    timestamp: str = None
    use_llm: bool = True

class AlertmanagerWebhook(BaseModel):
    alerts: list = []

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0", "time": datetime.utcnow().isoformat()}

@app.post("/run")
async def run(req: AlertRequest):
    alert = Alert(
        service=req.service, severity=req.severity,
        description=req.description,
        timestamp=datetime.fromisoformat(req.timestamp) if req.timestamp else datetime.utcnow()
    )
    try:
        result = await pipeline.run(alert)
        if req.use_llm:
            result = await run_llm_chain(result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhook")
async def webhook(payload: AlertmanagerWebhook):
    results = []
    for raw in payload.alerts:
        labels      = raw.get("labels", {})
        annotations = raw.get("annotations", {})
        alert = Alert(
            service=labels.get("service", labels.get("job", "unknown")),
            severity=labels.get("severity", "warning"),
            description=annotations.get("summary", labels.get("alertname", "alert")),
            timestamp=datetime.utcnow()
        )
        result = await pipeline.run(alert)
        result = await run_llm_chain(result)
        results.append(result)
    return {"processed": len(results), "results": results}

@app.get("/")
async def root():
    return {"endpoints": {"POST /run": "manual trigger", "POST /webhook": "alertmanager"}}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
