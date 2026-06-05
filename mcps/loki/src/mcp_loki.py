import httpx
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="MCP Loki")
# Loki desabilitado - retorna estrutura vazia
LOKI_ENABLED = False

class LogsRequest(BaseModel):
    service: str
    pattern: str = "error|Error|ERROR|exception|Exception|EXCEPTION"
    limit: int = 50
    lookback_minutes: int = 10

@app.post("/query")
async def query_logs(req: LogsRequest):
    if not LOKI_ENABLED:
        return {"status": "disabled", "data": {"resultType": "streams", "result": []}}
    
    # Código original (não vai executar)
    async with httpx.AsyncClient(timeout=30.0) as client:
        query = f'{{service_name="{req.service}"}} |= "{req.pattern}"'
        r = await client.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={"query": query, "limit": req.limit, "since": f"{req.lookback_minutes}m"}
        )
        return r.json() if r.status_code == 200 else {"error": r.text, "status": r.status_code}
