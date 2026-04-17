# Simple MCP Server on AgentCore Runtime

## Overview

This sample project demonstrates how to run a simple MCP server on Amazon Bedrock AgentCore Runtime.

## Tools Available

1. **add_numbers** — Add two numbers
2. **multiply_numbers** — Multiply two numbers
3. **divide_numbers** — Divide a number by another number
4. **power_numbers** — Raise a number to a power
5. **greet_user** — Greet a user by name in different languages
6. **calculate_statistics** — Compute mean, median, min, max, and standard deviation for a list of numbers
7. **format_text** — Format text using various string operations
8. **get_server_info** — Get information about the MCP server

## Quick Start

1. **Local Development**:
   ```bash
   cd simple-mcp
   pip install -r requirements.txt
   python simple_mcp_server.py
   ```

2. **Test Locally**:
   ```bash
   python simple_mcp_client_local.py
   ```

3. **Deploy to AgentCore**:
   ```bash
   python deploy_simple_mcp_server_on_agentcore_runtime.py
   ```

4. **Refresh Bearer Token**:
   ```bash
   python refresh_bearer_token.py
   ```

5. **Test Remote**:
   ```bash
   python simple_mcp_client_remote.py
   ```

6. **Run Scalability Test**:
   ```bash
   python simple_mcp_sequential_vs_parallel_test.py
   ```

## Project Files

| File | Description |
|------|-------------|
| `simple_mcp_server.py` | MCP server implementation with 8 tools |
| `simple_mcp_client_local.py` | Client for testing against a locally running server |
| `simple_mcp_client_remote.py` | Client for testing against the server deployed on AgentCore Runtime |
| `simple_mcp_sequential_vs_parallel_test.py` | Sequential vs concurrent comparison test |
| `deploy_simple_mcp_server_on_agentcore_runtime.py` | Deployment script (Cognito setup + AgentCore Runtime launch) |
| `refresh_bearer_token.py` | Refreshes the Cognito bearer token in Secrets Manager |

## Sequential vs Concurrent Test

`simple_mcp_sequential_vs_parallel_test.py` compares two execution modes with a user-specified number of requests:

| Mode | How It Works | Measures |
|------|--------------|----------|
| **Sequential** | Requests sent one after another | Baseline per-request latency |
| **Concurrent** | Requests fired simultaneously in batches of ≤25 (API rate limit) | Peak throughput, burst handling |

**Output:** Comparison table showing total time, success rate, avg/min/max response times, speedup factor, and batch breakdown.
