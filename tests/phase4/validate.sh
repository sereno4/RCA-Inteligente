#!/bin/bash
PASS=0; FAIL=0
check() {
  result=$(eval "$2" 2>&1)
  if echo "$result" | grep -q "$3"; then
    echo "  ✅ $1"; PASS=$((PASS+1))
  else
    echo "  ❌ $1 → $(echo $result | cut -c1-120)"; FAIL=$((FAIL+1))
  fi
}

echo "── Fase 4: LLM Chain + RAG ──"
echo ""

pkill -f "kubectl port-forward" 2>/dev/null; sleep 2
kubectl port-forward svc/rca-pipeline -n rca-system 8000:8000 &>/dev/null & PF=$!
sleep 4

echo "[ Pipeline ]"
check "health v2" "curl -sf http://localhost:8000/health" "2.0"

R1=$(curl -sf -X POST http://localhost:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"service":"checkout","severity":"critical","description":"High error rate on checkout, payment connection refused","use_llm":true}')

echo ""
echo "[ LLM Chain ]"
check "llm_chain presente" \
  "echo '$R1' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if d.get(\"llm_chain\") else \"missing\")'" "ok"
check "interpretation preenchida" \
  "echo '$R1' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if len(d[\"llm_chain\"][\"interpretation\"]) > 10 else \"vazio\")'" "ok"
check "hypotheses_narrative preenchida" \
  "echo '$R1' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if \"H1\" in d[\"llm_chain\"][\"hypotheses_narrative\"] else \"missing\")'" "ok"
check "validation preenchida" \
  "echo '$R1' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if len(d[\"llm_chain\"][\"validation\"]) > 10 else \"vazio\")'" "ok"

echo ""
echo "[ RAG ]"
check "similar incidents encontrados" \
  "echo '$R1' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if len(d.get(\"similar_incidents\",[])) > 0 else \"vazio\")'" "ok"

echo ""
echo "[ Performance ]"
check "elapsed < 10s" \
  "echo '$R1' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if d[\"elapsed_seconds\"] < 10 else \"lento\")'" "ok"

echo ""
echo "[ Relatório Markdown ]"
check "report gerado" \
  "echo '$R1' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if d.get(\"report\",\"\").startswith(\"# RCA\") else \"missing\")'" "ok"

R2=$(curl -sf -X POST http://localhost:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"service":"frontend","severity":"critical","description":"Recommendation cache miss causing product catalog overload and frontend slowness","use_llm":true}')

echo ""
echo "[ Caso difícil: cache cascade ]"
check "caso3 hipóteses geradas" \
  "echo '$R2' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if d.get(\"llm_chain\",{}).get(\"hypotheses_narrative\") else \"missing\")'" "ok"
check "caso3 RAG encontrou cache incident" \
  "echo '$R2' | python3 -c '
import sys,json
d=json.load(sys.stdin)
payloads = [s[\"payload\"].get(\"root_cause\",\"\") for s in d.get(\"similar_incidents\",[])]
print(\"ok\" if \"recommendation\" in payloads else \"miss\")
'" "ok"

kill $PF 2>/dev/null
wait 2>/dev/null

echo ""
echo "──────────────────────────────"
echo "  ${PASS} ✅  /  ${FAIL} ❌"
echo "──────────────────────────────"
[ $FAIL -eq 0 ] && exit 0 || exit 1
