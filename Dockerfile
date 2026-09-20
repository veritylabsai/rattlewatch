# syntax=docker/dockerfile:1
FROM python:3.13-slim

WORKDIR /app

# Only copy deps first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build the store at image build time so the container is ready to serve.
# Override with your own build step if you want a fresh feed at deploy time.
RUN python -m verity build --max-recalls 5000 || true

EXPOSE 8000

# Serve the REST API and MCP-over-HTTP on the same process.
CMD ["python", "-m", "verity", "serve", "--host", "0.0.0.0", "--port", "8000"]
