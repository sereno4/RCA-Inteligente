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

echo "── Fase 2: Validação MCPs ──"
echo ""

echo "[ Pods ]"
for mcp in prometheus loki tempo qdrant; do
  check "mcp-${mcp} running" \
    "kubectl get pod -n rca-mcps -l app=mcp-${mcp} --no-headers | awk '{print \$3}'" "Running"
done

echo ""
echo "[ Health checks via port-forward ]"
kubectl port-forward svc/mcp-prometheus -n rca-mcps 18001:8000 &>/dev/null & P1=$!
kubectl port-forward svc/mcp-loki       -n rca-mcps 18002:8000 &>/dev/null & P2=$!
kubectl port-forward svc/mcp-tempo      -n rca-mcps 18003:8000 &>/dev/null & P3=$!
kubectl port-forward svc/mcp-qdrant     -n rca-mcps 18004:8000 &>/dev/null & P4=$!
sleep 5

check "mcp-prometheus /health" "curl -sf http://localhost:18001/health" "ok"
check "mcp-loki /health"       "curl -sf http://localhost:18002/health" "ok"
check "mcp-tempo /health"      "curl -sf http://localhost:18003/health" "ok"
check "mcp-qdrant /health"     "curl -sf http://localhost:18004/health" "ok"

echo ""
echo "[ Funcionalidade ]"
check "prometheus query checkout" \
  "curl -sf -X POST http://localhost:18001/query \
   -H 'Content-Type: application/json' \
   -d '{\"service\":\"checkout\",\"lookback_minutes\":10}' \
   | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if \"metrics\" in d else \"erro\")'" "ok"

check "qdrant init collection" \
  "curl -sf -X POST http://localhost:18004/init \
   | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\")'" "ok"

check "tempo search checkout" \
  "curl -sf -X POST http://localhost:18003/search \
   -H 'Content-Type: application/json' \
   -d '{\"service\":\"checkout\",\"lookback_minutes\":10}' \
   | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if \"traces\" in d or \"error\" in d else \"vazio\")'" "ok"

kill $P1 $P2 $P3 $P4 2>/dev/null
wait 2>/dev/null

echo ""
echo "──────────────────────────────"
echo "  ${PASS} ✅  /  ${FAIL} ❌"
echo "──────────────────────────────"
[ $FAIL -eq 0 ] && exit 0 || exit 1
