import os
import json
import httpx
from typing import List, Dict

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
MODEL        = "llama-3.1-8b-instant"

async def _groq(system: str, user: str, max_tokens: int = 500) -> str:
    if not GROQ_API_KEY:
        return "[GROQ_API_KEY não configurada]"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": MODEL, "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system},
                                {"role": "user",   "content": user}]})
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return f"[Groq error {r.status_code}: {r.text[:100]}]"

async def llm1_interpret(alert_raw: dict) -> str:
    """Nó 1: traduz JSON do alerta em descrição clara"""
    system = (
        "You are an SRE alert interpreter. "
        "Given a raw alert JSON, produce ONE clear sentence describing "
        "what is failing and the observed symptom. Be concise, no markdown."
    )
    user = f"Alert JSON:\n{json.dumps(alert_raw, indent=2)}"
    return await _groq(system, user, max_tokens=120)

async def llm2_hypotheses(interpretation: str, causal_links: List[Dict],
                           evidence_summary: Dict, similar_incidents: List[Dict]) -> str:
    """Nó 2: gera hipóteses narrativas baseadas APENAS nas evidências matemáticas"""
    similar_text = ""
    if similar_incidents:
        similar_text = "\n\nSimilar past incidents:\n" + "\n".join(
            f"- [{s['payload'].get('original_id','?')}] {s['payload'].get('title','?')} "
            f"(score: {s['score']:.2f}) → root cause: {s['payload'].get('root_cause','?')}, "
            f"resolution: {s['payload'].get('resolution','?')}"
            for s in similar_incidents[:2]
        )

    causal_text = ""
    if causal_links:
        causal_text = "\n\nTemporal causal chain (sorted by time):\n" + "\n".join(
            f"- [{e['source']}] {e['service']}: {e['description'][:100]}"
            + (" ← EARLIEST EVENT" if e.get("is_root_candidate") else "")
            for e in causal_links[:5]
        )

    evidence_text = "\n\nEvidence summary per service:\n" + "\n".join(
        f"- {svc}: {ev['metrics_anomalies']} metric anomalies, "
        f"{ev['logs']} log streams, {ev['traces']} error traces"
        for svc, ev in evidence_summary.items()
    )

    system = (
        "You are an SRE root cause analyst. "
        "Generate EXACTLY 2-3 hypotheses based ONLY on the provided evidence. "
        "Do NOT invent evidence. Format each hypothesis as:\n"
        "H1 (confidence%): <root cause service> — <one sentence explanation>\n"
        "H2 (confidence%): ...\n"
        "H3 (confidence%): ... (optional)\n"
        "Keep each hypothesis under 20 words."
    )
    user = (
        f"Alert: {interpretation}"
        f"{evidence_text}"
        f"{causal_text}"
        f"{similar_text}"
    )
    return await _groq(system, user, max_tokens=300)

async def llm3_validate(interpretation: str, hypotheses_text: str,
                         causal_links: List[Dict]) -> str:
    """Nó 3: crítico — tenta quebrar as hipóteses e eliminar viés"""
    system = (
        "You are a skeptical SRE reviewer. "
        "Your job is to challenge the hypotheses below. "
        "For each hypothesis, state ONE reason it could be WRONG. "
        "Then pick the most defensible hypothesis and explain why in one sentence. "
        "Be brief and direct. No markdown."
    )
    evidence_available = bool(causal_links)
    user = (
        f"Alert: {interpretation}\n\n"
        f"Hypotheses to challenge:\n{hypotheses_text}\n\n"
        f"Evidence available: {'yes — ' + str(len(causal_links)) + ' causal events' if evidence_available else 'none — limited observability'}"
    )
    return await _groq(system, user, max_tokens=300)

async def run_llm_chain(pipeline_result: dict) -> dict:
    """Executa a cadeia de 3 LLMs sobre o resultado do pipeline determinístico"""
    alert        = pipeline_result["alert"]
    causal_links = pipeline_result.get("causal_links", [])
    evidence     = pipeline_result.get("evidence_summary", {})
    similar      = pipeline_result.get("similar_incidents", [])
    hypotheses   = pipeline_result.get("hypotheses", [])

    print("[LLM1] Interpretando alerta...")
    interpretation = await llm1_interpret(alert)
    print(f"[LLM1] {interpretation}")

    print("[LLM2] Gerando hipóteses narrativas...")
    hypotheses_text = await llm2_hypotheses(interpretation, causal_links, evidence, similar)
    print(f"[LLM2]\n{hypotheses_text}")

    print("[LLM3] Validando hipóteses...")
    validation = await llm3_validate(interpretation, hypotheses_text, causal_links)
    print(f"[LLM3]\n{validation}")

    # Ranking final: combina hipóteses determinísticas com narrativa LLM
    ranked = []
    for h in hypotheses:
        ranked.append({
            "rank":        h["rank"],
            "root_cause":  h["root_cause"],
            "confidence":  h["confidence"],
            "description": h["description"],
        })

    return {
        **pipeline_result,
        "llm_chain": {
            "interpretation": interpretation,
            "hypotheses_narrative": hypotheses_text,
            "validation": validation,
        },
        "hypotheses_ranked": ranked,
        "report": _build_report(alert, interpretation, hypotheses_text,
                                validation, pipeline_result)
    }

def _build_report(alert: dict, interpretation: str, hypotheses: str,
                  validation: str, pipeline_result: dict) -> str:
    impact = ", ".join(pipeline_result.get("impact_radius", []))
    elapsed = pipeline_result.get("elapsed_seconds", 0)
    similar = pipeline_result.get("similar_incidents", [])
    rag_line = ""
    if similar:
        top = similar[0]
        rag_line = (f"\n**Similar incident:** {top['payload'].get('title','?')} "
                    f"(score: {top['score']:.0%}) → "
                    f"{top['payload'].get('resolution','?')}")

    return f"""# RCA Report — {alert['service']}

**Alert:** {interpretation}
**Time:** {alert['time']}
**Analysis time:** {elapsed}s
**Impact radius:** {impact}
{rag_line}

## Hypotheses
{hypotheses}

## Validation
{validation}

## Evidence Summary
{_evidence_table(pipeline_result.get('evidence_summary', {}))}
"""

def _evidence_table(evidence: dict) -> str:
    if not evidence:
        return "_No evidence collected — check observability pipeline_"
    lines = ["| Service | Metric anomalies | Log streams | Error traces |",
             "|---------|-----------------|-------------|--------------|"]
    for svc, ev in evidence.items():
        lines.append(f"| {svc} | {ev['metrics_anomalies']} | {ev['logs']} | {ev['traces']} |")
    return "\n".join(lines)
