import asyncio
import json
import httpx
from datetime import datetime
from typing import List, Dict
from dataclasses import dataclass, field

@dataclass
class Alert:
    service: str
    severity: str
    description: str
    timestamp: datetime

@dataclass
class Hypothesis:
    rank: int
    description: str
    confidence: float
    evidence_ids: List[str] = field(default_factory=list)
    root_cause: str = ""

class BFSExplorer:
    """Delimita escopo via Prometheus — código puro, sem LLM"""
    SERVICE_GRAPH = {
        "frontend":       ["checkout", "recommendation", "ad", "shipping", "currency"],
        "checkout":       ["payment", "shipping", "currency", "cart", "email", "product-catalog"],
        "cart":           ["valkey-cart"],
        "recommendation": ["product-catalog"],
        "product-catalog":[""],
        "payment":        [""],
        "shipping":       [""],
    }

    def __init__(self, prometheus_mcp: str):
        self.prometheus_mcp = prometheus_mcp

    async def get_impact_radius(self, service: str, depth: int = 2) -> List[str]:
        visited, queue = {service}, [service]
        for _ in range(depth):
            next_level = []
            for svc in queue:
                for dep in self.SERVICE_GRAPH.get(svc, []):
                    if dep and dep not in visited:
                        visited.add(dep)
                        next_level.append(dep)
            queue = next_level

        # Poda: mantém só serviços com anomalia real
        suspicious = [service]
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = [self._has_anomaly(client, svc) for svc in visited if svc != service]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for svc, has_anomaly in zip([s for s in visited if s != service], results):
                if has_anomaly is True:
                    suspicious.append(svc)
        return suspicious

    async def _has_anomaly(self, client: httpx.AsyncClient, service: str) -> bool:
        try:
            r = await client.post(f"{self.prometheus_mcp}/anomalies",
                                  json={"service": service, "lookback_minutes": 10})
            if r.status_code == 200:
                return len(r.json().get("anomalies", [])) > 0
        except Exception:
            pass
        return False

class TemporalCorrelator:
    """Correlação determinística — matemática pura, sem LLM"""

    def correlate(self, evidences: Dict[str, Dict]) -> List[Dict]:
        all_events = []
        for service, ev in evidences.items():
            # Eventos de log
            for stream in ev.get("logs", {}).get("data", {}).get("result", [])[:5]:
                for ts, line in stream.get("values", [])[:3]:
                    all_events.append({
                        "id": f"L-{service}-{ts}",
                        "timestamp_ns": int(ts),
                        "source": "log",
                        "service": service,
                        "description": line[:150],
                        "is_root_candidate": False
                    })
            # Eventos de trace com erro
            for trace in ev.get("traces", {}).get("traces", [])[:5]:
                ts = trace.get("startTimeUnixNano", 0)
                if ts:
                    all_events.append({
                        "id": f"T-{service}-{ts}",
                        "timestamp_ns": int(ts),
                        "source": "trace",
                        "service": service,
                        "description": trace.get("rootName", "")[:150],
                        "is_root_candidate": False
                    })

        all_events.sort(key=lambda x: x["timestamp_ns"])

        # Heurística causal: evento mais antigo com erro = candidato a causa raiz
        for i, evt in enumerate(all_events[:10]):
            evt["is_root_candidate"] = (i == 0)
            # Causalidade temporal: se B ocorreu >30s antes de A, B causou A
            if i > 0:
                delta_s = (all_events[i]["timestamp_ns"] - all_events[0]["timestamp_ns"]) / 1e9
                evt["seconds_after_first"] = round(delta_s, 2)

        return all_events

class RAGMemory:
    """Busca incidentes similares no Qdrant — evidência primeiro, memória depois"""

    def __init__(self, qdrant_mcp: str):
        self.qdrant_mcp = qdrant_mcp

    def _simple_vector(self, text: str) -> List[float]:
        """Vetor determinístico simples (sem modelo de embedding — será substituído na Fase 4)"""
        import hashlib
        vec = [0.0] * 384
        for i, char in enumerate(text[:384]):
            vec[i % 384] += ord(char) / 1000.0
        norm = sum(x*x for x in vec) ** 0.5
        return [x / (norm + 1e-9) for x in vec]

    async def search_similar(self, description: str, limit: int = 3) -> List[Dict]:
        vector = self._simple_vector(description)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{self.qdrant_mcp}/search",
                                      json={"query_vector": vector, "limit": limit,
                                            "score_threshold": 0.5})
                if r.status_code == 200:
                    return r.json().get("result", [])
        except Exception as e:
            print(f"[RAG] Erro na busca: {e}")
        return []

    async def store_incident(self, incident_id: str, description: str, payload: dict):
        vector = self._simple_vector(description)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(f"{self.qdrant_mcp}/store",
                                  json={"id": incident_id, "vector": vector, "payload": payload})
        except Exception as e:
            print(f"[RAG] Erro ao salvar: {e}")

class RCAPipeline:
    def __init__(self):
        self.mcp_base      = "http://mcp-{}.rca-mcps.svc.cluster.local:8000"
        self.prometheus_mcp = self.mcp_base.format("prometheus")
        self.loki_mcp       = self.mcp_base.format("loki")
        self.tempo_mcp      = self.mcp_base.format("tempo")
        self.qdrant_mcp     = self.mcp_base.format("qdrant")
        self.bfs        = BFSExplorer(self.prometheus_mcp)
        self.correlator = TemporalCorrelator()
        self.rag        = RAGMemory(self.qdrant_mcp)

    async def run(self, alert: Alert) -> Dict:
        print(f"[PIPELINE] Iniciando RCA: {alert.service} — {alert.description}")
        start_time = datetime.utcnow()

        # PASSO 1: BFS — delimita escopo (código puro)
        impact_radius = await self.bfs.get_impact_radius(alert.service)
        print(f"[BFS] Raio de impacto: {impact_radius}")

        # PASSO 2: Coleta de evidências em paralelo via MCPs
        evidences = {}
        async with httpx.AsyncClient(timeout=20.0) as client:
            tasks = [self._collect(client, svc, alert) for svc in impact_radius]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for svc, ev in zip(impact_radius, results):
                if not isinstance(ev, Exception):
                    evidences[svc] = ev
                else:
                    print(f"[COLLECT] {svc}: {ev}")

        # PASSO 3: Correlação temporal determinística (matemática, não LLM)
        causal_links = self.correlator.correlate(evidences)
        print(f"[CORRELATE] {len(causal_links)} eventos correlacionados")

        # PASSO 4: RAG — evidência primeiro, memória depois
        similar_incidents = await self.rag.search_similar(alert.description)
        print(f"[RAG] {len(similar_incidents)} incidentes similares encontrados")

        # PASSO 5: Gera hipóteses (determinístico)
        hypotheses = self._hypotheses(alert, causal_links, evidences, similar_incidents)

        elapsed = (datetime.utcnow() - start_time).total_seconds()
        print(f"[PIPELINE] Concluído em {elapsed:.1f}s")

        return {
            "alert": {"service": alert.service, "description": alert.description,
                      "time": alert.timestamp.isoformat()},
            "elapsed_seconds": round(elapsed, 2),
            "impact_radius": impact_radius,
            "evidence_summary": {
                svc: {
                    "metrics_anomalies": len(ev.get("anomalies", {}).get("anomalies", [])),
                    "logs":   len(ev.get("logs",   {}).get("data", {}).get("result", [])),
                    "traces": len(ev.get("traces", {}).get("traces", []))
                } for svc, ev in evidences.items()
            },
            "causal_links": causal_links[:10],
            "similar_incidents": [
                {"score": s.get("score", 0),
                 "payload": s.get("payload", {})}
                for s in similar_incidents
            ],
            "hypotheses": [h.__dict__ for h in hypotheses]
        }

    async def _collect(self, client: httpx.AsyncClient, service: str, alert: Alert) -> Dict:
        metrics, logs, traces = {}, {}, {}
        try:
            r = await client.post(f"{self.prometheus_mcp}/anomalies",
                                  json={"service": service, "lookback_minutes": 10})
            metrics = r.json() if r.status_code == 200 else {}
        except Exception as e:
            print(f"[Prometheus MCP] {service}: {e}")
        try:
            r = await client.post(f"{self.loki_mcp}/errors",
                                  json={"service": service, "lookback_minutes": 10})
            logs = r.json() if r.status_code == 200 else {}
        except Exception as e:
            print(f"[Loki MCP] {service}: {e}")
        try:
            r = await client.post(f"{self.tempo_mcp}/errors",
                                  json={"service": service, "lookback_minutes": 10})
            traces = r.json() if r.status_code == 200 else {}
        except Exception as e:
            print(f"[Tempo MCP] {service}: {e}")
        return {"anomalies": metrics, "logs": logs, "traces": traces}

    def _hypotheses(self, alert: Alert, causal_links: List[Dict],
                    evidences: Dict, similar: List[Dict]) -> List["Hypothesis"]:
        h = []

        # H1: serviço com evento mais antigo na timeline
        if causal_links:
            root = causal_links[0]
            confidence = 0.80
            # Boost se incidente similar no RAG
            if similar and similar[0].get("score", 0) > 0.7:
                confidence = min(0.95, confidence + 0.15)
            h.append(Hypothesis(rank=1,
                description=f"Root cause: {root['service']} — {root['description'][:80]}",
                confidence=confidence,
                evidence_ids=[root["id"]],
                root_cause=root["service"]))

        # H2: degradação em cascata (múltiplos serviços com anomalia)
        services_with_anomaly = [
            svc for svc, ev in evidences.items()
            if ev.get("anomalies", {}).get("anomalies")
        ]
        if len(services_with_anomaly) > 1:
            h.append(Hypothesis(rank=2,
                description=f"Cascade failure: {', '.join(services_with_anomaly[:3])}",
                confidence=0.55,
                root_cause=services_with_anomaly[0]))

        # H3: fallback — bug interno
        h.append(Hypothesis(rank=len(h)+1,
            description=f"Internal bug in {alert.service}",
            confidence=0.20,
            root_cause=alert.service))

        return h

if __name__ == "__main__":
    async def test():
        result = await RCAPipeline().run(Alert(
            service="checkout", severity="critical",
            description="High error rate on checkout",
            timestamp=datetime.utcnow()))
        print(json.dumps(result, indent=2, default=str))
    asyncio.run(test())
