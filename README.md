# MCP Server Examples for Amazon Bedrock AgentCore

This repository contains example implementations of Model Context Protocol (MCP) servers designed to run on Amazon Bedrock AgentCore Runtime.

## Projects

### 🔧 [Simple MCP Server](./simple-mcp/)
A basic MCP server implementation demonstrating fundamental operations and tools.

**Tools:**
- `add_numbers`, `multiply_numbers`, `divide_numbers`, `power_numbers` — basic math operations
- `greet_user` — multilingual user greeting
- `calculate_statistics` — statistical calculations (mean, median, std dev, etc.)
- `format_text` — text formatting operations
- `get_server_info` — server metadata retrieval

**Use Case:** Getting started with MCP servers and understanding the basic concepts.

📖 **[View Simple MCP Documentation](./simple-mcp/README.md)**

---

### ⚡ [Long-Running MCP Server](./long-running-mcp/)
An advanced MCP server designed for handling large payloads and computationally intensive tasks.

**Tools:**
- `matrix_operations` — large matrix computations (multiply, eigenvalues, SVD, inverse) with configurable matrix size
- `monte_carlo_simulation` — Monte Carlo simulations (pi estimation, portfolio, integration)
- `prime_factorization` — prime factorization for large numbers
- `data_aggregation` — large dataset generation and statistical analysis with configurable payload sizes
- `hash_computation` — CPU-intensive iterative hashing (SHA-256, SHA-512, MD5) with configurable data size and iterations
- `get_server_status` — server health and resource monitoring

**Use Case:** Testing scalability, CPU stress, payload handling, and performance characteristics on AgentCore Runtime.

📖 **[View Long-Running MCP Documentation](./long-running-mcp/README.md)**

---

### 🧹 [Cleanup Script](./cleanup.py)
A common cleanup utility that detects and removes all AWS resources created by either deployment.

**Resources Cleaned:**
- AgentCore Runtime endpoints and agent runtimes
- Cognito User Pools and associated users
- Secrets Manager secrets
- SSM Parameter Store parameters
- ECR repositories
- IAM execution roles

**Usage:**
```bash
python cleanup.py
```

The script auto-detects which servers (simple-mcp, long-running-mcp, or both) are deployed, prompts for confirmation, then deletes all associated resources.

## Getting Started

### Deploy Both Servers (Recommended)

Use the master deployment script to deploy both MCP servers in one go:

```bash
python deploy-mcp-servers.py
```

The script will prompt you for a Cognito username and password, then deploy the simple MCP server followed by the long-running MCP server automatically.

### Deploy Individually

Each project can also be deployed independently. Set the credentials as environment variables first, then run the deployment script from within the project directory:

Below credentials are just an example, please use different credentials for your testing. 

```bash
export MCP_USERNAME='myuser'
export MCP_PASSWORD='MySecureP@ss1'

# Simple MCP server
cd simple-mcp
python deploy_simple_mcp_server_on_agentcore_runtime.py

# Long-running MCP server
cd long-running-mcp
python deploy_long_running_mcp_server_on_agentcore_runtime.py
```

Each project contains its own complete setup instructions, including:
- Local development setup
- Testing procedures
- Deployment to AgentCore Runtime

Choose the project that best fits your needs and follow the respective README for detailed instructions.

## Architecture

Both servers are built to run on Amazon Bedrock AgentCore Runtime and include:
- Docker containerization
- JWT authentication via Cognito
- Comprehensive logging and monitoring
- Stateless HTTP transport with session isolation

## Quick Navigation

- [Simple MCP Server Setup](./simple-mcp/README.md#quick-start)
- [Long-Running MCP Server Setup](./long-running-mcp/README.md#quick-start)
- [Deploy Both Servers](./deploy-mcp-servers.py)
- [Cleanup All Resources](./cleanup.py)

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.