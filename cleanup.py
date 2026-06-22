#!/usr/bin/env python3
"""
Cleanup script for Long-Running MCP Server AgentCore Runtime deployments.

Detects and removes all AWS resources created by the long-running-mcp
deployment scripts (baseline and optimized):
  - AgentCore Runtime endpoints and agent runtimes
  - Cognito User Pools
  - Secrets Manager secrets
  - SSM Parameter Store parameters
  - ECR repositories
  - IAM execution roles (Runtime + CodeBuild)
  - AgentCore Memory stores
  - Workload Identities
"""

import json
import os
import sys
import time

import boto3
from boto3.session import Session

# Deployment configurations for long-running MCP server variants
DEPLOYMENTS = {
    "long-running-mcp-baseline": {
        "agent_name": "long_running_mcp_server_baseline",
        "cognito_pool_name": "LongRunningMCPServerPoolBaseline",
        "secrets": ["long_running_mcp_server_baseline/cognito/credentials", "long_running_mcp_server_baseline/deploy/credentials"],
        "ssm_params": [
            "/long_running_mcp_server_baseline/runtime/agent_arn",
            "/long_running_mcp_server_baseline/metadata",
        ],
    },
    "long-running-mcp-optimized": {
        "agent_name": "long_running_mcp_server_optimized",
        "cognito_pool_name": "LongRunningMCPServerPoolOptimized",
        "secrets": ["long_running_mcp_server_optimized/cognito/credentials", "long_running_mcp_server_optimized/deploy/credentials"],
        "ssm_params": [
            "/long_running_mcp_server_optimized/runtime/agent_arn",
            "/long_running_mcp_server_optimized/metadata",
        ],
    },
}


def find_agent_runtime(agentcore_client, agent_name):
    """Find an agent runtime by name. Returns agent_runtime_id or None."""
    paginator = agentcore_client.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for rt in page.get("agentRuntimes", []):
            if rt.get("agentRuntimeName") == agent_name:
                return rt["agentRuntimeId"]
    return None


def delete_agent_runtime(agentcore_client, agent_runtime_id, agent_name):
    """Delete all endpoints then the agent runtime itself, waiting for completion."""
    # Delete non-default endpoints first (DEFAULT is removed automatically with the runtime)
    paginator = agentcore_client.get_paginator("list_agent_runtime_endpoints")
    for page in paginator.paginate(agentRuntimeId=agent_runtime_id):
        for ep in page.get("runtimeEndpoints", []):
            ep_name = ep["name"]
            if ep_name == "DEFAULT":
                print(f"  Skipping DEFAULT endpoint (auto-deleted with runtime)")
                continue
            print(f"  Deleting endpoint: {ep_name}")
            agentcore_client.delete_agent_runtime_endpoint(
                agentRuntimeId=agent_runtime_id, endpointName=ep_name
            )
            # Wait for endpoint deletion
            while True:
                try:
                    time.sleep(5)
                    eps = agentcore_client.list_agent_runtime_endpoints(
                        agentRuntimeId=agent_runtime_id
                    )
                    names = [e["name"] for e in eps.get("runtimeEndpoints", [])]
                    if ep_name not in names:
                        break
                except Exception:
                    break
            print(f"  ✓ Endpoint {ep_name} deleted")

    # Delete the runtime
    print(f"  Deleting agent runtime: {agent_name} ({agent_runtime_id})")
    agentcore_client.delete_agent_runtime(agentRuntimeId=agent_runtime_id)

    # Wait for runtime deletion
    while True:
        try:
            time.sleep(5)
            agentcore_client.get_agent_runtime(agentRuntimeId=agent_runtime_id)
        except agentcore_client.exceptions.ResourceNotFoundException:
            break
        except Exception:
            break
    print(f"  ✓ Agent runtime deleted")


def delete_cognito_pool(cognito_client, pool_name):
    """Find and delete a Cognito User Pool by name."""
    paginator = cognito_client.get_paginator("list_user_pools")
    for page in paginator.paginate(MaxResults=60):
        for pool in page.get("UserPools", []):
            if pool["Name"] == pool_name:
                pool_id = pool["Id"]
                # Must delete domain first if one exists
                try:
                    desc = cognito_client.describe_user_pool(UserPoolId=pool_id)
                    domain = desc["UserPool"].get("Domain")
                    if domain:
                        cognito_client.delete_user_pool_domain(
                            UserPoolId=pool_id, Domain=domain
                        )
                except Exception:
                    pass
                cognito_client.delete_user_pool(UserPoolId=pool_id)
                print(f"  ✓ Cognito User Pool deleted: {pool_name} ({pool_id})")
                return
    print(f"  - Cognito User Pool not found: {pool_name}")


def delete_secrets(secrets_client, secret_names):
    """Delete Secrets Manager secrets."""
    for name in secret_names:
        try:
            secrets_client.delete_secret(
                SecretId=name, ForceDeleteWithoutRecovery=True
            )
            print(f"  ✓ Secret deleted: {name}")
        except secrets_client.exceptions.ResourceNotFoundException:
            print(f"  - Secret not found: {name}")


def delete_ssm_params(ssm_client, param_names):
    """Delete SSM Parameter Store parameters."""
    for name in param_names:
        try:
            ssm_client.delete_parameter(Name=name)
            print(f"  ✓ SSM parameter deleted: {name}")
        except ssm_client.exceptions.ParameterNotFound:
            print(f"  - SSM parameter not found: {name}")


def delete_ecr_repo(ecr_client, agent_name):
    """Delete the ECR repository created by auto_create_ecr."""
    # The toolkit creates repos with a 'bedrock-agentcore-' prefix
    for repo_name in [
        f"bedrock-agentcore-{agent_name}",
        agent_name,
        f"{agent_name}-repo",
    ]:
        try:
            ecr_client.delete_repository(repositoryName=repo_name, force=True)
            print(f"  ✓ ECR repository deleted: {repo_name}")
            return
        except ecr_client.exceptions.RepositoryNotFoundException:
            continue
    print(f"  - ECR repository not found for: {agent_name}")


def _delete_iam_role(iam_client, role_name):
    """Detach all policies and delete a single IAM role."""
    # Detach managed policies
    paginator = iam_client.get_paginator("list_attached_role_policies")
    for page in paginator.paginate(RoleName=role_name):
        for p in page.get("AttachedPolicies", []):
            iam_client.detach_role_policy(RoleName=role_name, PolicyArn=p["PolicyArn"])
    # Delete inline policies
    paginator = iam_client.get_paginator("list_role_policies")
    for page in paginator.paginate(RoleName=role_name):
        for p_name in page.get("PolicyNames", []):
            iam_client.delete_role_policy(RoleName=role_name, PolicyName=p_name)
    iam_client.delete_role(RoleName=role_name)


def delete_execution_role(iam_client, agent_name, runtime_role_arn=None):
    """Delete IAM execution roles created by auto_create_execution_role.

    The toolkit creates roles named ``AmazonBedrockAgentCoreSDKRuntime-<region>-<hash>``
    and corresponding ``AmazonBedrockAgentCoreSDKCodeBuild-<region>-<hash>`` roles.
    If the runtime was still present when we inspected it, *runtime_role_arn* gives us
    the exact role name.  We also try legacy naming patterns as a fallback.
    """
    deleted = False

    # If we captured the role ARN from the runtime, use it directly
    if runtime_role_arn:
        role_name = runtime_role_arn.rsplit("/", 1)[-1]  # extract name from ARN
        try:
            _delete_iam_role(iam_client, role_name)
            print(f"  ✓ IAM Runtime role deleted: {role_name}")
            deleted = True
        except iam_client.exceptions.NoSuchEntityException:
            pass

        # The toolkit also creates a matching CodeBuild role with the same hash
        if "AmazonBedrockAgentCoreSDKRuntime-" in role_name:
            codebuild_role = role_name.replace(
                "AmazonBedrockAgentCoreSDKRuntime-", "AmazonBedrockAgentCoreSDKCodeBuild-"
            )
            try:
                _delete_iam_role(iam_client, codebuild_role)
                print(f"  ✓ IAM CodeBuild role deleted: {codebuild_role}")
                deleted = True
            except iam_client.exceptions.NoSuchEntityException:
                pass

    # Fallback: try legacy naming patterns
    for role_name in [
        f"{agent_name}-execution-role",
        f"{agent_name}-role",
        f"{agent_name}ExecutionRole",
    ]:
        try:
            _delete_iam_role(iam_client, role_name)
            print(f"  ✓ IAM role deleted: {role_name}")
            deleted = True
            break
        except iam_client.exceptions.NoSuchEntityException:
            continue

    if not deleted:
        print(f"  - IAM execution role not found for: {agent_name}")


def delete_memory(agentcore_client, agent_name):
    """Delete the AgentCore Memory auto-created for the agent."""
    try:
        paginator = agentcore_client.get_paginator("list_memories")
        for page in paginator.paginate():
            for mem in page.get("memories", []):
                mem_id = mem.get("id", "")
                # Memory IDs follow the pattern: <agent_name>_mem-<hash>
                if mem_id.startswith(f"{agent_name}_mem-"):
                    print(f"  Deleting memory: {mem_id}")
                    agentcore_client.delete_memory(memoryId=mem_id)
                    print(f"  ✓ Memory deleted: {mem_id}")
                    return
    except Exception:
        pass
    print(f"  - Memory not found for: {agent_name}")


def delete_workload_identity(agentcore_client, runtime_id):
    """Delete the Workload Identity auto-created for the agent runtime."""
    if not runtime_id:
        print("  - Workload Identity skipped (no runtime ID)")
        return
    try:
        agentcore_client.delete_workload_identity(
            workloadIdentityDirectoryId="default",
            name=runtime_id,
        )
        print(f"  ✓ Workload Identity deleted: {runtime_id}")
    except Exception:
        print(f"  - Workload Identity not found for: {runtime_id}")


def reset_agentcore_yaml(agent_name):
    """Reset .bedrock_agentcore.yaml to a clean state without stale agent IDs.

    After cleanup deletes the runtime, the YAML still contains the old agent_id/arn.
    The next deploy would try to 'update' a non-existent runtime and fail.
    This writes a minimal config so the next deploy creates a fresh runtime.
    """
    # Map agent name to its directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    variant_dirs = {
        "long_running_mcp_server_baseline": os.path.join(script_dir, "long-running-mcp", "baseline"),
        "long_running_mcp_server_optimized": os.path.join(script_dir, "long-running-mcp", "optimized"),
    }

    variant_dir = variant_dirs.get(agent_name)
    if not variant_dir:
        print(f"  - Cannot determine config path for: {agent_name}")
        return

    yaml_path = os.path.join(variant_dir, ".bedrock_agentcore.yaml")
    if not os.path.exists(yaml_path):
        print(f"  - YAML not found: {yaml_path}")
        return

    # Write minimal clean config
    clean_yaml = f"""default_agent: {agent_name}
agents:
  {agent_name}:
    name: {agent_name}
    entrypoint: long_running_mcp_server.py
    platform: linux/arm64
    container_runtime: none
    aws:
      region: us-east-1
      network_configuration:
        network_mode: PUBLIC
      protocol_configuration:
        server_protocol: MCP
      observability:
        enabled: true
    memory:
      mode: STM_ONLY
"""
    with open(yaml_path, "w") as f:
        f.write(clean_yaml)
    print(f"  ✓ Reset config: {yaml_path}")


def cleanup_deployment(region, server_type, config):
    """Clean up all resources for a single deployment."""
    agent_name = config["agent_name"]

    agentcore_client = boto3.client("bedrock-agentcore-control", region_name=region)
    cognito_client = boto3.client("cognito-idp", region_name=region)
    secrets_client = boto3.client("secretsmanager", region_name=region)
    ssm_client = boto3.client("ssm", region_name=region)
    ecr_client = boto3.client("ecr", region_name=region)
    iam_client = boto3.client("iam", region_name=region)

    # 1. AgentCore Runtime — capture role ARN before deletion
    print("\n  [AgentCore Runtime]")
    runtime_id = find_agent_runtime(agentcore_client, agent_name)
    runtime_role_arn = None
    if runtime_id:
        # Grab the role ARN from the runtime metadata before we delete it
        try:
            rt_info = agentcore_client.get_agent_runtime(agentRuntimeId=runtime_id)
            runtime_role_arn = rt_info.get("roleArn")
        except Exception:
            pass
        delete_agent_runtime(agentcore_client, runtime_id, agent_name)
    else:
        print(f"  - Agent runtime not found: {agent_name}")

    # 2. Cognito User Pool
    print("\n  [Cognito User Pool]")
    delete_cognito_pool(cognito_client, config["cognito_pool_name"])

    # 3. Secrets Manager
    print("\n  [Secrets Manager]")
    delete_secrets(secrets_client, config["secrets"])

    # 4. SSM Parameters
    print("\n  [SSM Parameter Store]")
    delete_ssm_params(ssm_client, config["ssm_params"])

    # 5. ECR Repository
    print("\n  [ECR Repository]")
    delete_ecr_repo(ecr_client, agent_name)

    # 6. IAM Execution Role
    print("\n  [IAM Execution Role]")
    delete_execution_role(iam_client, agent_name, runtime_role_arn)

    # 7. AgentCore Memory
    print("\n  [AgentCore Memory]")
    delete_memory(agentcore_client, agent_name)

    # 8. Workload Identity
    print("\n  [Workload Identity]")
    delete_workload_identity(agentcore_client, runtime_id)

    # 9. Reset .bedrock_agentcore.yaml to remove stale agent IDs
    print("\n  [Reset Config YAML]")
    reset_agentcore_yaml(agent_name)


def main():
    boto_session = Session()
    region = boto_session.region_name
    print(f"🌍 Region: {region}\n")
    print("🔍 Scanning for deployed MCP servers...")

    agentcore_client = boto3.client("bedrock-agentcore-control", region_name=region)

    found = {}
    for server_type, config in DEPLOYMENTS.items():
        runtime_id = find_agent_runtime(agentcore_client, config["agent_name"])
        if runtime_id:
            found[server_type] = config
            print(f"  ✓ Found: {server_type} (runtime: {runtime_id})")
        else:
            # Check if partial artifacts exist (secrets/params without runtime)
            secrets_client = boto3.client("secretsmanager", region_name=region)
            for secret_name in config["secrets"]:
                try:
                    secrets_client.describe_secret(SecretId=secret_name)
                    found[server_type] = config
                    print(f"  ✓ Found artifacts for: {server_type} (no active runtime)")
                    break
                except Exception:
                    pass
            if server_type not in found:
                print(f"  - Not found: {server_type}")

    if not found:
        print("\n✅ No deployments found. Nothing to clean up.")
        return

    # Confirm
    print(f"\n⚠️  Will delete ALL resources for: {', '.join(found.keys())}")
    confirm = input("Proceed? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    # Clean up each found deployment
    for server_type, config in found.items():
        print(f"\n{'='*60}")
        print(f"🧹 Cleaning up: {server_type}")
        print(f"{'='*60}")
        try:
            cleanup_deployment(region, server_type, config)
        except Exception as e:
            print(f"\n❌ Error cleaning up {server_type}: {e}")

    print(f"\n{'='*60}")
    print("🎉 Cleanup complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
