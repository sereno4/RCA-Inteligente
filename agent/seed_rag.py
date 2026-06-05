"""Popula o Qdrant com incidentes históricos para o RAG"""
import asyncio
import httpx

QDRANT_MCP = "http://localhost:18004"

INCIDENTS = [
    {
        "id": "INC-001",
        "description": "High error rate on checkout service, payment connection refused",
        "payload": {
            "title": "Checkout → Payment connection refused",
            "root_cause": "payment",
            "resolution": "Restart payment deployment, check network policy",
            "services_affected": ["checkout", "payment"],
            "duration_minutes": 12,
            "tags": ["connection", "payment", "checkout"]
        }
    },
    {
        "id": "INC-002",
        "description": "Cart service timeout causing checkout failures",
        "payload": {
            "title": "Cart timeout cascade to checkout",
            "root_cause": "cart",
            "resolution": "Increase cart service resources, fix valkey-cart memory limit",
            "services_affected": ["checkout", "cart", "valkey-cart"],
            "duration_minutes": 8,
            "tags": ["timeout", "cart", "cascade"]
        }
    },
    {
        "id": "INC-003",
        "description": "Recommendation cache miss causing product catalog overload",
        "payload": {
            "title": "Cache miss → catalog CPU spike → frontend slow",
            "root_cause": "recommendation",
            "resolution": "Restart recommendation service to rebuild cache",
            "services_affected": ["frontend", "recommendation", "product-catalog"],
            "duration_minutes": 25,
            "tags": ["cache", "recommendation", "catalog", "cascade"]
        }
    },
    {
        "id": "INC-004",
        "description": "Currency service 503 errors affecting checkout and frontend",
        "payload": {
            "title": "Currency service OOMKilled",
            "root_cause": "currency",
            "resolution": "Increase memory limit for currency service",
            "services_affected": ["checkout", "frontend", "currency"],
            "duration_minutes": 5,
            "tags": ["oom", "currency", "memory"]
        }
    },
    {
        "id": "INC-005",
        "description": "Shipping service high latency p99 > 5s",
        "payload": {
            "title": "Shipping external API degradation",
            "root_cause": "shipping",
            "resolution": "Shipping depends on external quote API — added circuit breaker",
            "services_affected": ["checkout", "shipping"],
            "duration_minutes": 35,
            "tags": ["latency", "shipping", "external"]
        }
    },
]

def simple_vector(text: str):
    vec = [0.0] * 384
    for i, char in enumerate(text[:384]):
        vec[i % 384] += ord(char) / 1000.0
    norm = sum(x*x for x in vec) ** 0.5
    return [x / (norm + 1e-9) for x in vec]

async def seed():
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Init collection
        r = await client.post(f"{QDRANT_MCP}/init")
        print(f"Collection init: {r.json()}")

        # Insere incidentes
        for inc in INCIDENTS:
            vector = simple_vector(inc["description"])
            r = await client.post(f"{QDRANT_MCP}/store", json={
                "id": inc["id"],
                "vector": vector,
                "payload": inc["payload"]
            })
            status = "✅" if r.json().get("stored") else "❌"
            print(f"{status} {inc['id']}: {inc['payload']['title']}")

    print(f"\nTotal: {len(INCIDENTS)} incidentes inseridos no Qdrant")

asyncio.run(seed())
