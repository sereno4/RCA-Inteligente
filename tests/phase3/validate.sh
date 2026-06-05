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

echo "── Fase 3: Pipeline Determinístico + RAG ──"
echo ""

pkill -f "kubectl port-forward" 2>/dev/null; sleep 2
kubectl port-forward svc/rca-pipeline -n rca-system 8000:8000 &>/dev/null & PF=$!
sleep 4

echo "[ Health ]"
check "pipeline up" "curl -sf http://localhost:8000/health" "ok"

echo ""
echo "[ Caso 1: checkout error ]"
RESULT1=$(curl -sf -X POST http://localhost:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"service":"checkout","severity":"critical","description":"High error rate on checkout, payment connection refused"}')
echo "$RESULT1" | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("  impact_radius:", d["impact_radius"])
print("  elapsed:", d["elapsed_seconds"], "s")
print("  hypotheses:", len(d["hypotheses"]))
print("  similar_incidents:", len(d["similar_incidents"]))
for h in d["hypotheses"]:
    print(f"    H{h[\"rank\"]} ({h[\"confidence\"]:.0%}): {h[\"description\"][:70]}")
'

echo ""
check "caso1 tem hipóteses" \
  "echo '$RESULT1' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if d[\"hypotheses\"] else \"vazio\")'" "ok"
check "caso1 elapsed < 30s" \
  "echo '$RESULT1' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if d[\"elapsed_seconds\"] < 30 else \"lento\")'" "ok"

echo ""
echo "[ Caso 2: cart timeout ]"
RESULT2=$(curl -sf -X POST http://localhost:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"service":"cart","severity":"warning","description":"Cart service timeout high"}')
echo "$RESULT2" | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("  impact_radius:", d["impact_radius"])
print("  hypotheses:", len(d["hypotheses"]))
for h in d["hypotheses"]:
    print(f"    H{h[\"rank\"]} ({h[\"confidence\"]:.0%}): {h[\"description\"][:70]}")
' 2>/dev/null

check "caso2 responde" \
  "echo '$RESULT2' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if \"hypotheses\" in d else \"erro\")'" "ok"

kill $PF 2>/dev/null
wait 2>/dev/null

echo ""
echo "──────────────────────────────"
echo "  ${PASS} ✅  /  ${FAIL} ❌"
echo "──────────────────────────────"
[ $FAIL -eq 0 ] && exit 0 || exit 1
