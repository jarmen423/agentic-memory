# Docker Setup Examples

This guide provides practical examples for deploying Agentic Memory using Docker and Docker Compose.

## Table of Contents

- [Quick Start](#quick-start)
- [Production Deployment](#production-deployment)
- [Development Setup](#development-setup)
- [Multi-Repository Setup](#multi-repository-setup)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

### Example 1: Neo4j Only (Simplest)

**Scenario:** You want to run Neo4j in Docker and Agentic Memory on your host machine.

**docker-compose.yml:**
```yaml
version: "3.8"

services:
  neo4j:
    image: neo4j:5.25-community
    container_name: agentic-memory-neo4j
    ports:
      - "7474:7474"  # HTTP (Neo4j Browser)
      - "7687:7687"  # Bolt (database connection)
    environment:
      NEO4J_AUTH: neo4j/change_this_password
      NEO4J_dbms_memory_heap_max__size: 2G
      NEO4J_dbms_memory_pagecache_size: 1G
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "neo4j", "-p", "change_this_password", "RETURN 1"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  neo4j_data:
    driver: local
```

**Usage:**
```bash
# Start Neo4j
docker-compose up -d

# Check logs
docker-compose logs -f neo4j

# Verify health
curl http://localhost:7474

# Initialize in your project
cd /path/to/your/project
codememory init

# Choose "Local Neo4j (Docker)" in the wizard
```

---

### Example 2: Full Stack (Neo4j + Agentic Memory)

**Scenario:** Run everything in Docker including the ingestion service.

**docker-compose.yml:**
```yaml
version: "3.8"

services:
  neo4j:
    image: neo4j:5.25-community
    container_name: agentic-memory-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/password
      NEO4J_dbms_memory_heap_max__size: 2G
      NEO4J_dbms_memory_pagecache_size: 1G
    volumes:
      - neo4j_data:/data
    networks:
      - agentic-memory-network

  ingestion:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: agentic-memory-ingestion
    volumes:
      # Mount your codebase here
      - /path/to/your/codebase:/workspace:ro
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: password
      OPENAI_API_KEY: ${OPENAI_API_KEY}
    command: ["python", "-m", "codememory.cli", "index", "/workspace"]
    depends_on:
      neo4j:
        condition: service_healthy
    networks:
      - agentic-memory-network

volumes:
  neo4j_data:
    driver: local

networks:
  agentic-memory-network:
    driver: bridge
```

**Usage:**
```bash
# Set environment variable
export OPENAI_API_KEY="sk-..."

# Build and start
docker-compose up --build

# View logs
docker-compose logs -f ingestion

# Stop
docker-compose down
```

---

## Production Deployment

### Example 3: Secure Production Setup

**Scenario:** Deploy Agentic Memory in production with proper security.

**docker-compose.prod.yml:**
```yaml
version: "3.8"

services:
  neo4j:
    image: neo4j:5.25-enterprise  # Or community for free
    container_name: agentic-memory-neo4j-prod
    ports:
      - "127.0.0.1:7474:7474"  # Bind to localhost only
      - "127.0.0.1:7687:7687"
    environment:
      # Use secrets management in real production
      NEO4J_AUTH: ${NEO4J_USER}/${NEO4J_PASSWORD}
      NEO4J_dbms_memory_heap_max__size: 4G
      NEO4J_dbms_memory_pagecache_size: 2G
      NEO4J_dbms_ssl_policy_bolt_enabled: "true"
      NEO4J_dbms_connector_bolt_advertised__address: "localhost:7687"
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
      - ./neo4j/plugins:/plugins
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "${NEO4J_USER}", "-p", "${NEO4J_PASSWORD}", "RETURN 1"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - agentic-memory-network
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  ingestion:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: agentic-memory-ingestion-prod
    volumes:
      - /var/lib/jenkins/workspace:/workspace:ro  # Jenkins workspace
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: ${NEO4J_USER}
      NEO4J_PASSWORD: ${NEO4J_PASSWORD}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      LOG_LEVEL: INFO
    command: ["python", "-m", "codememory.cli", "watch", "/workspace"]
    depends_on:
      neo4j:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - agentic-memory-network
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  neo4j_data:
    driver: local
  neo4j_logs:
    driver: local

networks:
  agentic-memory-network:
    driver: bridge
```

**.env file:**
```bash
# Neo4j Configuration
NEO4J_USER=neo4j
NEO4J_PASSWORD=<strong_password_here>

# OpenAI Configuration
OPENAI_API_KEY=sk-...
```

**Usage:**
```bash
# Secure the .env file
chmod 600 .env

# Deploy
docker-compose -f docker-compose.prod.yml up -d

# Check logs
docker-compose -f docker-compose.prod.yml logs -f

# Backup Neo4j data
docker exec agentic-memory-neo4j-prod neo4j-admin database dump \
  --to-path=/backup \
  --database=neo4j
```

---

### Example 4: Multi-Stage Build for Smaller Images

**Dockerfile:**
```dockerfile
# Agentic Memory - Multi-stage Dockerfile
# Build: docker build -t agentic-memory .
# Run:   docker run -v /path/to/code:/workspace agentic-memory index /workspace

# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python packages to temporary location
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local

# Make sure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY pyproject.toml ./
COPY src/ ./src/

# Install in editable mode (minimal dependencies)
RUN pip install --no-cache-dir -e .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Default command
ENTRYPOINT ["python", "-m", "codememory.cli"]
CMD ["--help"]
```

**Build and run:**
```bash
# Build image
docker build -t agentic-memory:latest .

# Run indexing
docker run --rm \
  -v /path/to/code:/workspace \
  -e NEO4J_URI=bolt://host.docker.internal:7687 \
  -e NEO4J_USER=neo4j \
  -e NEO4J_PASSWORD=password \
  -e OPENAI_API_KEY=sk-... \
  agentic-memory:latest index /workspace

# Run MCP server
docker run -d \
  -p 8000:8000 \
  -v /path/to/code:/workspace \
  -e NEO4J_URI=bolt://host.docker.internal:7687 \
  -e NEO4J_USER=neo4j \
  -e NEO4J_PASSWORD=password \
  -e OPENAI_API_KEY=sk-... \
  --name agentic-memory-server \
  agentic-memory:latest serve --port 8000
```

---

## Development Setup

### Example 5: Development with Hot Reload

**Scenario:** You're developing Agentic Memory and want to test changes quickly.

**docker-compose.dev.yml:**
```yaml
version: "3.8"

services:
  neo4j:
    image: neo4j:5.25-community
    container_name: agentic-memory-dev-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/dev
      NEO4J_dbms_memory_heap_max__size: 1G
    volumes:
      - neo4j_dev_data:/data
    networks:
      - dev-network

  # Development service with mounted source code
  dev:
    build:
      context: .
      dockerfile: Dockerfile.dev
    container_name: agentic-memory-dev
    volumes:
      # Mount source code for hot reload
      - ./src:/app/src:ro
      # Mount test codebase
      - ./test-repo:/workspace:ro
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: dev
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      LOG_LEVEL: DEBUG
    command: ["python", "-m", "codememory.cli", "watch", "/workspace"]
    depends_on:
      - neo4j
    networks:
      - dev-network
    # Keep container running for interactive use
    stdin_open: true
    tty: true

volumes:
  neo4j_dev_data:
    driver: local

networks:
  dev-network:
    driver: bridge
```

**Dockerfile.dev:**
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install development dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    git \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir pytest pytest-cov mypy ruff black

# Copy source (will be mounted as volume in dev)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

ENTRYPOINT ["python", "-m", "codememory.cli"]
```

**Usage:**
```bash
# Start development environment
docker-compose -f docker-compose.dev.yml up -d

# Attach to dev container
docker exec -it agentic-memory-dev bash

# Inside container, run commands
codememory status
codememory search "test"

# View logs
docker-compose -f docker-compose.dev.yml logs -f dev

# Stop
docker-compose -f docker-compose.dev.yml down

# Clean volumes
docker-compose -f docker-compose.dev.yml down -v
```

---

## Multi-Repository Setup

### Example 6: Indexing Multiple Repositories

**Scenario:** You have multiple repositories and want to index them all.

**docker-compose.multi.yml:**
```yaml
version: "3.8"

services:
  neo4j:
    image: neo4j:5.25-community
    container_name: agentic-memory-multi-neo4j
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/password
      NEO4J_dbms_memory_heap_max__size: 4G
      NEO4J_dbms_memory_pagecache_size: 2G
    volumes:
      - neo4j_multi_data:/data
    networks:
      - multi-network

  # Indexer for repo 1
  indexer-repo1:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: agentic-memory-indexer-repo1
    volumes:
      - /path/to/repo1:/workspace:ro
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: password
      OPENAI_API_KEY: ${OPENAI_API_KEY}
    command: ["python", "-m", "codememory.cli", "index", "/workspace"]
    depends_on:
      - neo4j
    networks:
      - multi-network

  # Indexer for repo 2
  indexer-repo2:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: agentic-memory-indexer-repo2
    volumes:
      - /path/to/repo2:/workspace:ro
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: password
      OPENAI_API_KEY: ${OPENAI_API_KEY}
    command: ["python", "-m", "codememory.cli", "index", "/workspace"]
    depends_on:
      - neo4j
    networks:
      - multi-network

  # MCP server for all repos
  mcp-server:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: agentic-memory-mcp-server
    ports:
      - "8000:8000"
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: password
      OPENAI_API_KEY: ${OPENAI_API_KEY}
    command: ["python", "-m", "codememory.cli", "serve", "--port", "8000"]
    depends_on:
      - neo4j
    networks:
      - multi-network

volumes:
  neo4j_multi_data:
    driver: local

networks:
  multi-network:
    driver: bridge
```

**Usage:**
```bash
# Index all repos
docker-compose -f docker-compose.multi.yml up --build

# When done, stop indexers but keep server running
docker-compose -f docker-compose.multi.yml stop indexer-repo1 indexer-repo2

# Restart MCP server only
docker-compose -f docker-compose.multi.yml restart mcp-server
```

---

## Docker Tips and Tricks

### Tip 1: Using Docker Networks

```yaml
# Custom network for better isolation
networks:
  agentic-memory-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
```

---

### Tip 2: Resource Limits

```yaml
services:
  neo4j:
    # ... other config ...
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '1.0'
          memory: 2G
```

---

### Tip 3: Automatic Backups

```yaml
services:
  backup:
    image: neo4j:5.25-community
    container_name: agentic-memory-backup
    volumes:
      - neo4j_data:/data
      - ./backups:/backups
    environment:
      NEO4J_AUTH: neo4j/password
    command: >
      sh -c "
        neo4j-admin database dump \
          --to-path=/backups \
          --database=neo4j
      "
    depends_on:
      - neo4j
```

**Add to crontab:**
```bash
# Daily backup at 2 AM
0 2 * * * cd /path/to/agentic-memory && docker-compose run backup
```

---

### Tip 4: Health Check Scripts

**script/check_health.sh:**
```bash
#!/bin/bash
# Check if all services are healthy

echo "Checking Neo4j..."
docker exec agentic-memory-neo4j cypher-shell -u neo4j -p password "RETURN 1" || exit 1

echo "Checking MCP server..."
curl -f http://localhost:8000/health || exit 1

echo "All services healthy!"
```

---

### Tip 5: Logging Configuration

```yaml
services:
  ingestion:
    # ... other config ...
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
        labels: "service=ingestion,environment=production"
```

---

## Troubleshooting

### Issue: Container Can't Connect to Neo4j

**Symptom:** `ServiceUnavailable: Unable to connect to bolt://neo4j:7687`

**Solution 1: Check network**
```bash
# Verify containers are on same network
docker network inspect agentic-memory-network

# Should see both neo4j and ingestion containers
```

**Solution 2: Use service name as hostname**
```yaml
# Correct
NEO4J_URI: bolt://neo4j:7687

# Wrong (won't work)
NEO4J_URI: bolt://localhost:7687
```

**Solution 3: Wait for health check**
```yaml
depends_on:
  neo4j:
    condition: service_healthy  # Wait for healthy, not just started
```

---

### Issue: Volume Permission Denied

**Symptom:** `Permission denied: /data/neo4j`

**Solution:**
```bash
# Fix volume permissions
docker-compose down
docker volume rm agentic-memory_neo4j_data
docker-compose up -d

# Or change volume owner
docker exec -u root agentic-memory-neo4j chown -R neo4j:neo4j /data
```

---

### Issue: Out of Memory

**Symptom:** Container exits with code 137

**Solution:**
```yaml
# Increase memory limits
environment:
  NEO4J_dbms_memory_heap_max__size: 4G

# Or use Docker resource limits
deploy:
  resources:
    limits:
      memory: 6G
```

---

### Issue: Slow Indexing

**Symptom:** Indexing takes very long in Docker

**Solution 1: Use bind mounts instead of volumes**
```yaml
volumes:
  - /path/to/on/host:/workspace:ro  # Faster than named volume
```

**Solution 2: Increase resources**
```yaml
deploy:
  resources:
    limits:
      cpus: '4.0'
      memory: 8G
```

**Solution 3: Use Docker build cache**
```bash
docker build --cache-from=agentic-memory:latest -t agentic-memory .
```

---

## Quick Reference

### Common Commands

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down

# Stop and remove volumes
docker-compose down -v

# Rebuild after changes
docker-compose up -d --build

# Execute command in container
docker exec -it agentic-memory-ingestion bash

# Check resource usage
docker stats

# Inspect network
docker network inspect agentic-memory-network

# Backup Neo4j
docker exec agentic-memory-neo4j neo4j-admin database dump --to-path=/backup

# Restore Neo4j
docker exec agentic-memory-neo4j neo4j-admin database load --from-path=/backup --database=neo4j
```

---

**Next Steps:**
- [Main Installation Guide](../docs/INSTALLATION.md)
- [Basic Usage Examples](basic_usage.md)
- [Architecture Documentation](../docs/ARCHITECTURE.md)
