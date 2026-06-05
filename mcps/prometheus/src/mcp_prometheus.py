from fastapi import FastAPI
from pydantic import BaseModel
import httpx, os

app = FastAPI(title="MCP Prometheus")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL",
  "http://kube-prometheus-stack-prometheus.rca-monitoring.svc.cluster.local:9090")

class MetricRequest(BaseModel):
    service: str
    lookback_minutes: int = 10

@app.get("/health")
async def health():
    return {"status": "ok", "backend": PROMETHEUS_URL}

@app.post("/query")
async def query_metrics(req: MetricRequest):
    queries = {
        "error_rate": f'rate(http_server_duration_milliseconds_count{{service_name="{req.service}",http_response_status_code=~"4..|5.."}}[{req.lookback_minutes}m])',
        "latency_p99": f'histogram_quantile(0.99, rate(http_server_duration_milliseconds_bucket{{service_name="{req.service}"}}[{req.lookback_minutes}m]))',
        "rpc_errors":  f'rate(rpc_client_duration_milliseconds_count{{service_name="{req.service}",rpc_grpc_status_code!="0"}}[{req.lookback_minutes}m])',
    }
    results = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, promql in queries.items():
            try:
                r = await client.get(f"{PROMETHEUS_URL}/api/v1/query",
                                     params={"query": promql})
                results[name] = r.json().get("data", {}) if r.status_code == 200 else {}
            except Exception as e:
                results[name] = {"error": str(e)}
    return {"service": req.service, "metrics": results}

@app.post("/anomalies")
async def detect_anomalies(req: MetricRequest):
    """Detecta anomalias deterministicamente — sem LLM"""
    anomalies = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Error rate > 5%
        q = f'rate(http_server_duration_milliseconds_count{{service_name="{req.service}",http_response_status_code=~"5.."}}[5m]) / rate(http_server_duration_milliseconds_count{{service_name="{req.service}"}}[5m]) > 0.05'
        try:
            r = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": q})
            if r.status_code == 200 and r.json()["data"]["result"]:
                anomalies.append({"type": "high_error_rate", "service": req.service, "severity": "critical"})
        except Exception:
            pass
        # Latência p99 > 1s
        q2 = f'histogram_quantile(0.99, rate(http_server_duration_milliseconds_bucket{{service_name="{req.service}"}}[5m])) > 1000'
        try:
            r = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": q2})
            if r.status_code == 200 and r.json()["data"]["result"]:
                anomalies.append({"type": "high_latency_p99", "service": req.service, "severity": "warning"})
        except Exception:
            pass
    return {"service": req.service, "anomalies": anomalies}
