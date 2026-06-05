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

echo "── Fase 1: Validação Final ──"
echo ""

echo "[ Stack rca-monitoring ]"
check "prometheus" \
  "kubectl get pod -n rca-monitoring -l app.kubernetes.io/name=prometheus --no-headers | awk '{print \$3}'" "Running"
check "tempo" \
  "kubectl get pod -n rca-monitoring -l app.kubernetes.io/name=tempo --no-headers | awk '{print \$3}'" "Running"
check "qdrant" \
  "kubectl get pod -n rca-monitoring -l app.kubernetes.io/name=qdrant --no-headers | awk '{print \$3}'" "Running"
check "loki" \
  "kubectl get pod -n rca-monitoring -l app.kubernetes.io/name=loki --no-headers | awk '{print \$3}'" "Running"

echo ""
echo "[ OTel Demo — 24 serviços ]"
check "checkout rodando" \
  "kubectl get pod -n rca-otel-demo -l app.kubernetes.io/component=checkout --no-headers | awk '{print \$3}'" "Running"
check "frontend rodando" \
  "kubectl get pod -n rca-otel-demo -l app.kubernetes.io/component=frontend --no-headers | awk '{print \$3}'" "Running"
check "cart rodando" \
  "kubectl get pod -n rca-otel-demo -l app.kubernetes.io/component=cart --no-headers | awk '{print \$3}'" "Running"
check "total pods running" \
  "kubectl get pods -n rca-otel-demo --no-headers | grep -c Running" "2"

echo ""
echo "[ RCA Pipeline ]"
check "pod running" \
  "kubectl get pod -n rca-system -l app=rca-pipeline --no-headers | awk '{print \$3}'" "Running"

echo ""
echo "[ APIs ]"
kubectl port-forward svc/kube-prometheus-stack-prometheus -n rca-monitoring 9090:9090 &>/dev/null & PF1=$!
kubectl port-forward svc/loki -n rca-monitoring 3100:3100 &>/dev/null & PF2=$!
kubectl port-forward svc/tempo -n rca-monitoring 3200:3200 &>/dev/null & PF3=$!
kubectl port-forward svc/rca-pipeline -n rca-system 8000:8000 &>/dev/null & PF4=$!
sleep 5

check "prometheus healthy" \
  "curl -sf http://localhost:9090/-/healthy" "Prometheus"
check "loki ready" \
  "curl -sf http://localhost:3100/ready" "ready"
check "tempo ready" \
  "curl -sf http://localhost:3200/ready" "ready"
check "pipeline health" \
  "curl -sf http://localhost:8000/health" "ok"

echo ""
echo "[ Métricas no Prometheus ]"
check "métricas kubernetes existem" \
  "curl -sf 'http://localhost:9090/api/v1/query?query=kube_pod_info' \
   | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if d[\"data\"][\"result\"] else \"vazio\")'" "ok"
check "otel-demo pods visíveis" \
  "curl -sf 'http://localhost:9090/api/v1/query?query=kube_pod_info{namespace=\"rca-otel-demo\"}' \
   | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if d[\"data\"][\"result\"] else \"vazio\")'" "ok"

echo ""
echo "[ Pipeline BFS ]"
check "pipeline responde /run" \
  "curl -sf -X POST http://localhost:8000/run \
   -H 'Content-Type: application/json' \
   -d '{\"service\":\"checkout\",\"severity\":\"critical\",\"description\":\"High error rate\"}' \
   | python3 -c 'import sys,json; d=json.load(sys.stdin); print(\"ok\" if \"hypotheses\" in d else \"erro\")'" "ok"

kill $PF1 $PF2 $PF3 $PF4 2>/dev/null
wait 2>/dev/null

echo ""
echo "──────────────────────────────"
echo "  ${PASS} ✅  /  ${FAIL} ❌"
echo "──────────────────────────────"
[ $FAIL -eq 0 ] && exit 0 || exit 1
