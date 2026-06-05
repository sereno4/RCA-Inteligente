FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn httpx
ARG MCP_NAME
COPY ${MCP_NAME}/src/ ./
CMD ["sh", "-c", "uvicorn mcp_${MCP_NAME}:app --host 0.0.0.0 --port 8000"]
