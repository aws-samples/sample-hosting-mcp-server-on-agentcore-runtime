#!/usr/bin/env python3
"""
Master Deployment Script for MCP Servers on AgentCore Runtime.

This script orchestrates the deployment of both the simple MCP server
and the long-running MCP server to Amazon Bedrock AgentCore Runtime.

It prompts the user for Cognito credentials, sets them as environment
variables, and then runs each deployment script sequentially.
"""

import getpass
import os
import subprocess
import sys


def get_user_credentials():
    """Prompt the user for Cognito username and password."""
    print("=" * 60)
    print("🔐 MCP Server Deployment - Credential Setup")
    print("=" * 60)
    print("\nEnter the Cognito credentials to use for both MCP servers.\n")

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


def get_deployment_choice():
    """Prompt the user to choose which server(s) to deploy."""
    print("\nWhich MCP server(s) would you like to deploy?\n")
    print("  1. Simple MCP Server")
    print("  2. Long-Running MCP Server")
    print("  3. Both\n")

    choice = input("Enter your choice (1/2/3): ").strip()
    if choice not in ("1", "2", "3"):
        print("❌ Invalid choice. Please enter 1, 2, or 3.")
        sys.exit(1)

    return choice


def main():
    choice = get_deployment_choice()
    username, password = get_user_credentials()

    # Set credentials as environment variables for child processes
    os.environ["MCP_USERNAME"] = username
    os.environ["MCP_PASSWORD"] = password

    project_root = os.path.dirname(os.path.abspath(__file__))

    simple_ok = None
    long_ok = None

    # Deploy simple MCP server
    if choice in ("1", "3"):
        simple_ok = run_deployment(
            script_path=os.path.join(project_root, "simple-mcp", "deploy_simple_mcp_server_on_agentcore_runtime.py"),
            cwd=os.path.join(project_root, "simple-mcp"),
            label="Simple MCP Server",
        )
        if not simple_ok and choice == "3":
            print("\n⚠️  Simple MCP Server deployment failed. Continuing with long-running server...")

    # Deploy long-running MCP server
    if choice in ("2", "3"):
        long_ok = run_deployment(
            script_path=os.path.join(project_root, "long-running-mcp", "deploy_long_running_mcp_server_on_agentcore_runtime.py"),
            cwd=os.path.join(project_root, "long-running-mcp"),
            label="Long-Running MCP Server",
        )

    # Summary
    print(f"\n{'=' * 60}")
    print("📋 Deployment Summary")
    print(f"{'=' * 60}")
    if simple_ok is not None:
        print(f"  Simple MCP Server:       {'✅ Success' if simple_ok else '❌ Failed'}")
    if long_ok is not None:
        print(f"  Long-Running MCP Server: {'✅ Success' if long_ok else '❌ Failed'}")
    print(f"{'=' * 60}")

    if (simple_ok is not None and not simple_ok) or (long_ok is not None and not long_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
