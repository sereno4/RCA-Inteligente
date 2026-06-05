from fastapi import FastAPI
from pydantic import BaseModel
import httpx, os, hashlib
from typing import List

app = FastAPI(title="MCP Qdrant")
QDRANT_URL = os.getenv("QDRANT_URL",
  "http://qdrant.rca-monitoring.svc.cluster.local:6333")
COLLECTION = "rca_incidents"

class SearchRequest(BaseModel):
    query_vector: List[float]
    limit: int = 3
    score_threshold: float = 0.5

class StoreRequest(BaseModel):
    id: str
    vector: List[float]
    payload: dict

def str_to_int_id(s: str) -> int:
    """Converte string ID para int estável via hash"""
    return int(hashlib.md5(s.encode()).hexdigest()[:8], 16)

@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            r = await client.get(f"{QDRANT_URL}/healthz")
            return {"status": "ok", "qdrant": r.status_code == 200}
        except Exception as e:
            return {"status": "error", "detail": str(e)}

@app.post("/init")
async def init_collection():
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Tenta criar — ignora se já existe
        r = await client.put(f"{QDRANT_URL}/collections/{COLLECTION}", json={
            "vectors": {"size": 384, "distance": "Cosine"}
        })
        exists = "already exists" in r.text
        return {"created": r.status_code in (200, 201) or exists,
                "detail": r.text[:100]}

@app.post("/store")
async def store_incident(req: StoreRequest):
    int_id = str_to_int_id(req.id)
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.put(
                f"{QDRANT_URL}/collections/{COLLECTION}/points",
                json={"points": [{"id": int_id, "vector": req.vector,
                                  "payload": {**req.payload, "original_id": req.id}}]}
            )
            return {"stored": r.status_code in (200, 201), "int_id": int_id,
                    "detail": r.text[:100]}
        except Exception as e:
            return {"stored": False, "error": str(e)}

@app.post("/search")
async def search_similar(req: SearchRequest):
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
                json={"vector": req.query_vector, "limit": req.limit,
                      "score_threshold": req.score_threshold,
                      "with_payload": True}
            )
            return r.json() if r.status_code == 200 else {"result": [], "error": r.text[:200]}
        except Exception as e:
            return {"result": [], "error": str(e)}
