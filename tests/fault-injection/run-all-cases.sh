#!/bin/bash
PIPELINE="http://localhost:8000"

call_agent() {
  local service=$1 desc=$2
  echo ""
  echo ">>> Agente analisando: $service"
  curl -sf -X POST $PIPELINE/run \
    -H 'Content-Type: application/json' \
    -d "{\"service\":\"$service\",\"severity\":\"critical\",\"description\":\"$desc\",\"use_llm\":true}" \
    | python3 -c '
import sys, json
d = json.load(sys.stdin)
llm = d.get("llm_chain", {})
print("  INTERPRETATION:", llm.get("interpretation","—"))
print("  ELAPSED:", d.get("elapsed_seconds"), "s")
print("  IMPACT RADIUS:", d.get("impact_radius"))
print("  SIMILAR:", len(d.get("similar_incidents",[])), "incidents")
print("  HYPOTHESES:")
for line in llm.get("hypotheses_narrative","—").split("\n"):
    if line.strip(): print("   ", line)
print("  VALIDATION:")
for line in llm.get("validation","—").split("\n")[-4:]:
    if line.strip(): print("   ", line)
'
}

pkill -f "kubectl port-forward" 2>/dev/null; sleep 2
kubectl port-forward svc/rca-pipeline -n rca-system 8000:8000 &>/dev/null &
PF=$!
sleep 4

echo "════════════════════════════════"
echo " CASO 1: checkout → payment bloqueado"
echo "════════════════════════════════"
kubectl apply -f ~/rca-agent/tests/fault-injection/case1-network-policy.yaml
sleep 15
call_agent "checkout" "High RPC error rate to payment service, connection refused"
kubectl delete -f ~/rca-agent/tests/fault-injection/case1-network-policy.yaml
echo "==> Restaurado"

sleep 5

echo ""
echo "════════════════════════════════"
echo " CASO 2: cart derrubado → checkout falha"
echo "════════════════════════════════"
kubectl scale deployment cart -n rca-otel-demo --replicas=0
sleep 20
call_agent "checkout" "Checkout failing, cart service unavailable timeout"
kubectl scale deployment cart -n rca-otel-demo --replicas=1
echo "==> Restaurado"

sleep 5

echo ""
echo "════════════════════════════════"
echo " CASO 3: recommendation OOM → catalog → frontend"
echo "════════════════════════════════"
kubectl patch deployment recommendation -n rca-otel-demo --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"10Mi"}]'
sleep 25
call_agent "frontend" "Frontend high latency, recommendation cache miss, product catalog overload"
kubectl patch deployment recommendation -n rca-otel-demo --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"200Mi"}]'
echo "==> Restaurado"

kill $PF 2>/dev/null; wait 2>/dev/null
echo ""
echo "════════════════════════════════"
echo " Todos os casos executados!"
echo "════════════════════════════════"
