#!/bin/bash

# Build MCPs
for mcp in prometheus loki tempo qdrant; do
    echo "Building MCP-$mcp..."
    docker build -t mcp-$mcp:latest --build-arg MCP_NAME=$mcp -f mcps/Dockerfile mcps/
    kind load docker-image mcp-$mcp:latest --name ai-governance
done

# Build MCP Server
docker build -t mcp-server:latest -f mcps/Dockerfile mcps/
kind load docker-image mcp-server:latest --name ai-governance

# Build Pipeline
docker build -t rca-pipeline:latest -f agent/Dockerfile agent/
kind load docker-image rca-pipeline:latest --name ai-governance

echo "Done!"
