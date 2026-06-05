#!/bin/bash
set -e

echo "==> Adicionando repos Helm..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

echo "==> Criando namespaces..."
kubectl create namespace rca-monitoring --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace rca-otel-demo  --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace rca-system --dry-run=client -o yaml | kubectl apply -f -

echo "==> Instalando kube-prometheus-stack..."
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace rca-monitoring \
  --values infra/helm-values/kube-prometheus-stack.yaml \
  --wait --timeout 10m

echo "==> Instalando Loki..."
helm upgrade --install loki grafana/loki \
  --namespace rca-monitoring \
  --values infra/helm-values/loki.yaml \
  --wait --timeout 10m

echo "==> Instalando Tempo..."
helm upgrade --install tempo grafana/tempo \
  --namespace rca-monitoring \
  --values infra/helm-values/tempo.yaml \
  --wait --timeout 10m

echo "==> Instalando OTel Demo App..."
helm upgrade --install otel-demo open-telemetry/opentelemetry-demo \
  --namespace rca-otel-demo \
  --values infra/helm-values/otel-demo.yaml \
  --wait --timeout 15m

echo ""
echo "✅ Instalação concluída!"
echo "   Grafana:    http://localhost:30300  (admin/admin)"
echo "   Prometheus: http://localhost:30090"
echo "   OTel Demo:  http://localhost:30080"
