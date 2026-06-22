# Hosting MCP Server on Amazon Bedrock AgentCore Runtime

This repository demonstrates how to deploy and optimize a Long-Running MCP (Model Context Protocol) server on Amazon Bedrock AgentCore Runtime. It includes a baseline server and an optimized server variant, along with test suites that measure the impact of both server-side and client-side optimizations.

## Project Structure

```
sample-hosting-mcp-server-on-agentcore-runtime/
├── deploy-mcp-servers.py                      # Deploys both baseline + optimized servers
├── cleanup.py                                 # Removes all deployed AWS resources + resets configs
├── long-running-mcp/
│   ├── baseline/
│   │   ├── long_running_mcp_server.py         # Baseline MCP server (eager imports, sync tools)
│   │   ├── deploy_long_running_mcp_server_on_agentcore_runtime.py  # Deployment script for baseline
│   │   ├── Dockerfile                         # Container definition (identical to optimized)
│   │   ├── requirements.txt                   # Python dependencies (identical to optimized)
│   │   ├── refresh_bearer_token.py            # Utility to refresh expired Cognito tokens
│   │   └── .bedrock_agentcore.yaml            # AgentCore runtime configuration
│   ├── optimized/
│   │   ├── long_running_mcp_server.py         # Optimized MCP server (lazy loading, async, streaming)
│   │   ├── deploy_long_running_mcp_server_on_agentcore_runtime.py  # Deployment script for optimized
│   │   ├── Dockerfile                         # Container definition (identical to baseline)
│   │   ├── requirements.txt                   # Python dependencies (identical to baseline)
│   │   ├── refresh_bearer_token.py            # Utility to refresh expired Cognito tokens
│   │   └── .bedrock_agentcore.yaml            # AgentCore runtime configuration
│   ├── client-side-tests/
│   │   ├── long_running_mcp_sequential_vs_parallel_test.py  # Sequential vs concurrent batching comparison
│   │   ├── long_running_mcp_client_remote.py  # Full remote integration test (discovers + runs all tools)
│   │   ├── long_running_mcp_client_local.py   # Local dev client with interactive mode
│   │   ├── long_running_mcp_cpu_stress.py     # CPU stress test at configurable concurrency
│   │   └── long_running_mcp_payload_test.py   # Payload size scaling test (0.5MB → 10MB)
│   └── server-side-optimisation-tests/
│       └── baseline_vs_optimized_client.py    # Apples-to-apples server comparison (same client strategy)
└── images/
    └── architecture-diagram.png               # Architecture diagram
```

---

## MCP Server

### Tools Available

| Tool | Description |
|------|-------------|
| `matrix_operations` | Large matrix computations (multiply, eigenvalues, SVD, inverse) |
| `monte_carlo_simulation` | Monte Carlo simulations (pi estimation, portfolio, integration) |
| `prime_factorization` | Large number prime factorization |
| `data_aggregation` | Process and aggregate large datasets (statistical, groupby, clustering) |
| `hash_computation` | Compute hashes with configurable iterations (SHA-256, SHA-512, MD5) |
| `long_running_analysis` | Multi-stage analysis with progress streaming (optimized only) |
| `get_server_status` | Server health and resource monitoring |

---

## Server-Side Optimizations

The optimized server implements two key optimization techniques over the baseline:

### 1. Lazy Loading

Heavy scientific libraries are deferred from container startup to first actual use:

| Library | Baseline | Optimized |
|---------|----------|-----------|
| NumPy | `import numpy as np` at startup | Loaded on first use via `_get_numpy()` |
| Pandas | `import pandas as pd` at startup | Loaded on first use via `_get_pandas()` |
| SciPy | `from scipy import stats` at startup | Loaded on first use via `_get_scipy_stats()` |
| scikit-learn | `from sklearn.cluster import KMeans` at startup | Loaded on first use via `_get_kmeans()` |

**Benefit:** Reduces cold-start time by few seconds. Tools that don't need these libraries (like `get_server_status`) respond immediately without waiting for unused imports to complete.

### 2. Result Streaming via Progress Notifications

Long-running tools in the optimized server use FastMCP's `ctx.report_progress()` and `ctx.info()` to send real-time progress updates every 5 seconds during execution. The baseline server stays completely silent until the final result is ready.

**Benefit:** Clients receive feedback within ~5 seconds instead of waiting 30+ seconds in silence. This prevents client-side timeouts, enables progress indicators, and provides operational visibility without separate log access. The `long_running_analysis` tool is specifically designed to demonstrate this — it runs for 30 seconds across 6 stages and reports progress at each stage boundary.

---

## Prerequisites

### Python Virtual Environment Setup

The deployment and test scripts require several Python packages. Create a virtual environment and install dependencies:

```bash
cd sample-hosting-mcp-server-on-agentcore-runtime

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install deployment dependencies
pip3 install bedrock-agentcore bedrock-agentcore-starter-toolkit boto3 mcp httpx

# Install test/server dependencies
pip3 install numpy scipy pandas scikit-learn psutil anyio starlette requests
```

### AWS Configuration

Ensure AWS credentials are configured with access to:
- Amazon Bedrock AgentCore
- Amazon Cognito
- AWS Secrets Manager
- AWS Systems Manager (SSM)
- Amazon ECR
- AWS IAM
- AWS CodeBuild

```bash
aws configure
# Or set AWS_PROFILE / AWS_REGION environment variables
```

---

## Deployment

### Deploy Both Servers

```bash
python deploy-mcp-servers.py
```

Prompts for Cognito credentials (or reads from `MCP_USERNAME`/`MCP_PASSWORD` env vars) and deploys both variants as separate AgentCore runtimes.

| Variant | Runtime Name | Key Difference |
|---------|--------------|----------------|
| Baseline | `long_running_mcp_server_baseline` | Eager imports, sync tools, no streaming |
| Optimized | `long_running_mcp_server_optimized` | Lazy loading, async tools, progress streaming |

### Deploy Individually

```bash
export MCP_USERNAME='testuser'
export MCP_PASSWORD='TestUser@432'

# Baseline
cd long-running-mcp/baseline
python deploy_long_running_mcp_server_on_agentcore_runtime.py

# Optimized
cd long-running-mcp/optimized
python deploy_long_running_mcp_server_on_agentcore_runtime.py
```

---

## Testing

### 1. Server-Side Optimisation Tests

**Location:** `long-running-mcp/server-side-optimisation-tests/`

Compares baseline vs optimized server using an **identical client strategy** (sequential, new session per request). Any performance difference comes purely from the server code.

```bash
cd long-running-mcp/server-side-optimisation-tests

# Default — tests long_running_analysis (demonstrates streaming)
python baseline_vs_optimized_client.py --warm-requests 2

# Test lazy loading with a lightweight tool
python baseline_vs_optimized_client.py --tool monte_carlo_simulation --warm-requests 5

# Test all tools
python baseline_vs_optimized_client.py --all-tools --warm-requests 2

# Skip cold-start (servers already warm)
python baseline_vs_optimized_client.py --skip-cold-start --warm-requests 5
```

**What it measures:**
- Cold-start latency (where lazy loading has most impact)
- Warm latency (steady-state after libraries are loaded)
- Streaming behavior annotations for tools that demonstrate progress notifications

**Tools and optimization impact:**
| Tool | Lazy Load | Streaming | Best demonstrates |
|------|-----------|-----------|-------------------|
| `long_running_analysis` | No | Yes | Progress streaming (30s, 6 stages) |
| `monte_carlo_simulation` | Yes (NumPy) | Yes | Lazy loading (fast execution, clear cold-start delta) |
| `matrix_operations` | Yes (NumPy) | Yes | Streaming during compute (30s operation) |
| `data_aggregation` | Yes (Pandas + NumPy) | No | Lazy loading for multiple libraries |
| `get_server_status` | No | No | Cold-start savings (no libs needed at all) |
| `hash_computation` | No | Yes | Streaming during CPU-bound work |

### 2. Client-Side Tests

**Location:** `long-running-mcp/client-side-tests/`

Tests different **client calling strategies** and **server performance characteristics** against the deployed MCP server.

#### Client Optimisation

| Script | Purpose |
|--------|---------|
| `long_running_mcp_sequential_vs_parallel_test.py` | Compares sequential vs concurrent batched requests (respects 25 TPS AgentCore rate limit). Demonstrates that client-side concurrency can reduce wall time by 5–10x. |

```bash
cd long-running-mcp/client-side-tests
python long_running_mcp_sequential_vs_parallel_test.py
# Prompts for iteration count, runs both modes, prints comparison table
```

#### Server Performance Tests

| Script | Purpose |
|--------|---------|
| `long_running_mcp_cpu_stress.py` | Fires concurrent CPU-intensive requests (matrix SVD, hash computation) to test container scaling and resource limits |
| `long_running_mcp_payload_test.py` | Tests server behavior with increasing payload sizes (0.5MB → 10MB) using `data_aggregation` |
| `long_running_mcp_client_remote.py` | Full integration test — discovers all tools and runs each with representative parameters |
| `long_running_mcp_client_local.py` | Local development client with interactive mode for manual testing |

---

## Cleanup

```bash
python cleanup.py
```

Scans for deployed resources, prompts for confirmation, then removes:
- AgentCore Runtime endpoints and agent runtimes
- Cognito User Pools and users
- Secrets Manager secrets
- SSM Parameter Store parameters
- ECR repositories
- IAM execution roles (Runtime + CodeBuild)
- AgentCore Memory stores
- Workload Identities

Also **resets `.bedrock_agentcore.yaml`** files to a clean state so the next deployment creates fresh runtimes without stale agent ID errors.

---

## Architecture

The server runs on Amazon Bedrock AgentCore Runtime with:
- Docker containerization (Python 3.12 + uv package manager)
- JWT authentication via Amazon Cognito
- Stateless HTTP transport (streamable-http)
- OpenTelemetry instrumentation for observability
- ARM64 (Graviton) architecture via CodeBuild

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
