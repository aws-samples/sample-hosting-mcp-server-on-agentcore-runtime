#!/usr/bin/env python3
"""
Master Deployment Script for Long-Running MCP Server on AgentCore Runtime.

This script orchestrates the deployment of both the baseline and optimized
variants of the long-running MCP server to Amazon Bedrock AgentCore Runtime.

It prompts the user for Cognito credentials, sets them as environment
variables, and then runs each deployment script sequentially.

Each variant is deployed as a separate runtime:
- long_running_mcp_server_baseline
- long_running_mcp_server_optimized
"""

import getpass
import os
import subprocess
import sys


def get_user_credentials():
    """Get Cognito credentials from environment variables or interactive prompt."""
    username = os.environ.get("MCP_USERNAME", "").strip()
    password = os.environ.get("MCP_PASSWORD", "").strip()

    if username and password:
        print("=" * 60)
        print("🔐 Long-Running MCP Server Deployment - Credential Setup")
        print("=" * 60)
        print(f"\n✓ Using credentials from environment variables (MCP_USERNAME={username})\n")
        return username, password

    print("=" * 60)
    print("🔐 Long-Running MCP Server Deployment - Credential Setup")
    print("=" * 60)
    print("\nEnter the Cognito credentials to use for the MCP servers.\n")

    username = input("Username: ").strip()
    password = getpass.getpass("Password: ").strip()

    if not username or not password:
        print("❌ Username and password cannot be empty.")
        sys.exit(1)

    return username, password


def run_deployment(script_path, cwd, label):
    """Run a deployment script as a subprocess.

    Args:
        script_path: Path to the Python deployment script.
        cwd: Working directory to run the script from.
        label: Human-readable label for logging.

    Returns:
        True if the deployment succeeded, False otherwise.
    """
    print(f"\n{'=' * 60}")
    print(f"🚀 Deploying: {label}")
    print(f"{'=' * 60}\n")

    result = subprocess.run(
        [sys.executable, script_path],
        cwd=cwd,
        env=os.environ.copy(),
    )

    if result.returncode != 0:
        print(f"\n❌ {label} deployment failed (exit code {result.returncode})")
        return False

    print(f"\n✅ {label} deployment completed successfully")
    return True


def main():
    username, password = get_user_credentials()

    # Set credentials as environment variables for child processes
    os.environ["MCP_USERNAME"] = username
    os.environ["MCP_PASSWORD"] = password

    project_root = os.path.dirname(os.path.abspath(__file__))

    # Deploy long-running MCP server (baseline)
    baseline_ok = run_deployment(
        script_path=os.path.join(project_root, "long-running-mcp", "baseline", "deploy_long_running_mcp_server_on_agentcore_runtime.py"),
        cwd=os.path.join(project_root, "long-running-mcp", "baseline"),
        label="Long-Running MCP Server (Baseline)",
    )

    # Deploy long-running MCP server (optimized)
    optimized_ok = run_deployment(
        script_path=os.path.join(project_root, "long-running-mcp", "optimized", "deploy_long_running_mcp_server_on_agentcore_runtime.py"),
        cwd=os.path.join(project_root, "long-running-mcp", "optimized"),
        label="Long-Running MCP Server (Optimized)",
    )

    # Summary
    print(f"\n{'=' * 60}")
    print("📋 Deployment Summary")
    print(f"{'=' * 60}")
    print(f"  Long-Running MCP Server (Baseline):  {'✅ Success' if baseline_ok else '❌ Failed'}")
    print(f"  Long-Running MCP Server (Optimized): {'✅ Success' if optimized_ok else '❌ Failed'}")
    print(f"{'=' * 60}")

    if not baseline_ok or not optimized_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
