FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn httpx
COPY pipeline.py pipeline_http.py llm_chain.py .
CMD ["python", "pipeline_http.py"]
