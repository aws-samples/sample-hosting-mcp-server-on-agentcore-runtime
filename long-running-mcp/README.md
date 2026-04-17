# Long-Running MCP Server on AgentCore Runtime

## Overview

This MCP server demonstrates handling of large payloads and computationally intensive tasks on Amazon Bedrock AgentCore Runtime. It's designed to test scalability and performance characteristics with heavy workloads.

## Tools Available

1. **matrix_operations** — Large matrix computations (multiply, eigenvalues, SVD, inverse) with configurable matrix size
2. **monte_carlo_simulation** — Monte Carlo simulations (pi estimation, portfolio, integration)
3. **prime_factorization** — Prime factorization for large numbers using trial division
4. **data_aggregation** — Large dataset generation and statistical analysis (statistical, groupby, clustering)
5. **hash_computation** — CPU-intensive iterative hashing (SHA-256, SHA-512, MD5) with configurable data size and iterations
6. **get_server_status** — Server health and resource monitoring

## Quick Start

1. **Local Development**:
   ```bash
   cd long-running-mcp
   pip install -r requirements.txt
   python long_running_mcp_server.py
   ```

2. **Test Locally**:
   ```bash
   python long_running_mcp_client_local.py --interactive
   ```

3. **Deploy to AgentCore**:
   ```bash
   python deploy_long_running_mcp_server_on_agentcore_runtime.py
   ```

4. **Refresh Bearer Token**:
   ```bash
   python refresh_bearer_token.py
   ```

5. **Test Remote**:
   ```bash
   python long_running_mcp_client_remote.py
   ```

6. **Run Tests**:
   ```bash
   # Payload size scaling test
   python long_running_mcp_payload_test.py

   # Sequential vs concurrent comparison
   python long_running_mcp_sequential_vs_parallel_test.py

   # CPU stress test
   python long_running_mcp_cpu_stress.py
   ```

## Project Files

| File | Description |
|------|-------------|
| `long_running_mcp_server.py` | MCP server implementation with 6 computational tools |
| `long_running_mcp_client_local.py` | Client for testing against a locally running server |
| `long_running_mcp_client_remote.py` | Client for testing against the server deployed on AgentCore Runtime |
| `long_running_mcp_payload_test.py` | Payload size scaling test (0.5MB → 10MB) |
| `long_running_mcp_sequential_vs_parallel_test.py` | Sequential vs concurrent comparison test |
| `long_running_mcp_cpu_stress.py` | CPU stress test with heavy matrix SVD and hash computation |
| `deploy_long_running_mcp_server_on_agentcore_runtime.py` | Deployment script (Cognito setup + AgentCore Runtime launch) |
| `refresh_bearer_token.py` | Refreshes the Cognito bearer token in Secrets Manager |

## Testing Strategies

### Payload Size Test (`long_running_mcp_payload_test.py`)

Tests increasing payload sizes using the `data_aggregation` tool with a fixed 1-minute duration:

| Payload | Tool | Duration |
|---------|------|----------|
| 0.5MB → 1MB → 2MB → 3MB → 5MB → 10MB | `data_aggregation` | 1 min each |

**What it validates:** Server memory capacity, AgentCore container memory limits, and transport/streaming limits at different payload sizes.

### Sequential vs Concurrent Test (`long_running_mcp_sequential_vs_parallel_test.py`)

Compares sequential vs concurrent execution with a user-specified number of requests:

| Mode | How It Works | Measures |
|------|--------------|----------|
| **Sequential** | Requests sent one after another | Baseline per-request latency |
| **Concurrent** | Requests fired simultaneously in batches of ≤25 (API rate limit) | Peak throughput, burst handling |

**Test configuration:** N × `matrix_operations` (200×200 multiply, 30s each). The script prompts for the iteration count.

**What it validates:** True parallelism, whether concurrent requests route to same or different containers, resource isolation, and burst handling.

### CPU Stress Test (`long_running_mcp_cpu_stress.py`)

Runs aggressive CPU-intensive workloads on a single Runtime instance:

| Test | Tool | Parameters |
|------|------|------------|
| Matrix SVD (NumPy) | `matrix_operations` | 2000×2000 SVD, 5 min |
| Hash Computation (Pure CPU) | `hash_computation` | 10MB SHA-512, 5000 iterations multiplier, 5 min |

**What it validates:** Sustained CPU performance, memory under heavy load, and Runtime container resource limits.

## Configuration

### Execution Time
Tools accept a `duration_minutes` parameter (0.5 to 30 minutes).

### Payload Size
- `data_size_mb` — Size of data to process
- `matrix_size` — Dimensions for matrix operations
- `iterations_multiplier` — Number of hash iterations per cycle
