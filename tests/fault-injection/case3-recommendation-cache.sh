#!/bin/bash
kubectl patch deployment recommendation -n rca-otel-demo --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"10Mi"}]'
