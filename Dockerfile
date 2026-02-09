# Agentic Memory - Dockerfile
# Build: docker build -t agentic-memory .
# Run:   docker run -v /path/to/code:/workspace agentic-memory index /workspace

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy package files
COPY pyproject.toml ./
COPY requirements.txt ./
COPY src/ ./src/

# Install package
RUN pip install --no-cache-dir -e .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# Default command shows help
ENTRYPOINT ["python", "-m", "codememory.cli"]
CMD ["--help"]
