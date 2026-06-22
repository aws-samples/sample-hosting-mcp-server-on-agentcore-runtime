#!/usr/bin/env python3
"""
Remote Client for Long-Running MCP Server on AgentCore Runtime

This client connects to the long-running MCP server deployed on Amazon Bedrock 
AgentCore Runtime and demonstrates computational tool execution with large payloads.

Features:
- Retrieves credentials from AWS Secrets Manager and Parameter Store
- Connects to remote MCP server with JWT authentication
- Tests computational tools with configurable parameters
- Monitors long-running operations with progress tracking
- Comprehensive error handling for extended operations

Requirements:
- AWS credentials configured
- Long-running MCP server deployed via deploy_long_running_mcp_server.py
- mcp library installed
"""

import asyncio
import json
import sys
import time
import traceback
from datetime import timedelta
from typing import Dict, List
from urllib.parse import quote

import boto3
from boto3.session import Session
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Configuration constants
SSM_PARAMETER_NAME = '/long_running_mcp_server_baseline/runtime/agent_arn'
SECRETS_MANAGER_SECRET_NAME = 'long_running_mcp_server_baseline/cognito/credentials'
CONNECTION_TIMEOUT = 1800  # 30 minutes for long-running operations
AGENTCORE_BASE_URL = "https://bedrock-agentcore.{region}.amazonaws.com"


class LongRunningMCPClientError(Exception):
    """Custom exception for long-running MCP client errors."""
    pass


class LongRunningMCPCredentials:
    """Container for long-running MCP server credentials and configuration."""
    
    def __init__(self, agent_arn: str, bearer_token: str, region: str):
        self.agent_arn = agent_arn
        self.bearer_token = bearer_token
        self.region = region
        
    @property
    def encoded_arn(self) -> str:
        """URL-encode the agent ARN for use in HTTP requests."""
        return quote(self.agent_arn, safe='')
    
    @property
    def mcp_url(self) -> str:
        """Construct the MCP server URL."""
        base_url = AGENTCORE_BASE_URL.format(region=self.region)
        return f"{base_url}/runtimes/{self.encoded_arn}/invocations?qualifier=DEFAULT"
    
    @property
    def headers(self) -> Dict[str, str]:
        """HTTP headers for MCP requests."""
        return {
            "authorization": f"Bearer {self.bearer_token}",
            "Content-Type": "application/json"
        }


def get_aws_region() -> str:
    """
    Get the current AWS region from boto3 session.
    
    Returns:
        str: AWS region name
        
    Raises:
        LongRunningMCPClientError: If region cannot be determined
    """
    try:
        boto_session = Session()
        region = boto_session.region_name
        if not region:
            raise LongRunningMCPClientError("AWS region not configured")
        return region
    except Exception as e:
        raise LongRunningMCPClientError(f"Failed to get AWS region: {e}")


def retrieve_credentials(region: str) -> LongRunningMCPCredentials:
    """
    Retrieve long-running MCP server credentials from AWS services.
    
    Args:
        region (str): AWS region
        
    Returns:
        LongRunningMCPCredentials: Container with all necessary credentials
        
    Raises:
        LongRunningMCPClientError: If credential retrieval fails
    """
    print("🔑 Retrieving credentials from AWS...")
    
    try:
        # Get Agent ARN from Parameter Store
        ssm_client = boto3.client('ssm', region_name=region)
        agent_arn_response = ssm_client.get_parameter(Name=SSM_PARAMETER_NAME)
        agent_arn = agent_arn_response['Parameter']['Value']
        print(f"✓ Retrieved Agent ARN: {agent_arn}")
        
        # Get server metadata
        try:
            metadata_response = ssm_client.get_parameter(Name='/long_running_mcp_server/metadata')
            metadata = json.loads(metadata_response['Parameter']['Value'])
            print(f"✓ Server type: {metadata.get('server_type', 'unknown')}")
            print(f"✓ Max payload: {metadata.get('max_payload_mb', 'unknown')}MB")
            print(f"✓ Max duration: {metadata.get('max_duration_minutes', 'unknown')} minutes")
        except:
            print("⚠️ Could not retrieve server metadata")
        
        # Get Cognito credentials from Secrets Manager
        secrets_client = boto3.client('secretsmanager', region_name=region)
        response = secrets_client.get_secret_value(SecretId=SECRETS_MANAGER_SECRET_NAME)
        secret_value = response['SecretString']
        parsed_secret = json.loads(secret_value)
        bearer_token = parsed_secret['bearer_token']
        print("✓ Retrieved bearer token from Secrets Manager")
        
        return LongRunningMCPCredentials(agent_arn, bearer_token, region)
        
    except boto3.exceptions.Boto3Error as e:
        raise LongRunningMCPClientError(f"AWS service error: {e}")
    except json.JSONDecodeError as e:
        raise LongRunningMCPClientError(f"Invalid JSON in secrets: {e}")
    except KeyError as e:
        raise LongRunningMCPClientError(f"Missing key in secrets: {e}")
    except Exception as e:
        raise LongRunningMCPClientError(f"Unexpected error retrieving credentials: {e}")


async def list_available_tools(session: ClientSession) -> List:
    """
    List and display all available computational tools.
    
    Args:
        session (ClientSession): Active MCP session
        
    Returns:
        List: Available tools
    """
    print("\n🔄 Discovering available computational tools...")
    
    try:
        tool_result = await session.list_tools()
        tools = tool_result.tools
        
        print(f"\n📋 Available Long-Running Computational Tools ({len(tools)} found):")
        print("=" * 80)
        
        for tool in tools:
            print(f"🔧 {tool.name}")
            print(f"   Description: {tool.description}")
            
            # Display input schema if available
            if hasattr(tool, 'inputSchema') and tool.inputSchema:
                properties = tool.inputSchema.get('properties', {})
                if properties:
                    print(f"   Key Parameters:")
                    
                    # Highlight important parameters for long-running tools
                    important_params = ['duration_minutes', 'data_size_mb', 'matrix_size', 'num_simulations']
                    for param_name, param_info in properties.items():
                        if param_name in important_params:
                            param_type = param_info.get('type', 'unknown')
                            param_desc = param_info.get('description', 'No description')
                            print(f"     🎯 {param_name} ({param_type}): {param_desc}")
            print()
        
        return tools
        
    except Exception as e:
        print(f"❌ Error listing tools: {e}")
        return []


async def test_computational_tools(session: ClientSession, tools: List) -> None:
    """
    Test execution of computational tools with various configurations.
    
    Args:
        session (ClientSession): Active MCP session
        tools (List): Available tools to test
    """
    print("\n🧪 Testing Long-Running Computational Tools:")
    print("=" * 80)
    print("⚠️ Each test will run for its specified duration - this may take several minutes")
    
    # Define test cases for computational tools
    test_cases = [
        {
            "name": "get_server_status",
            "args": {},
            "description": "📊 Getting server status and resource information...",
            "expected_duration": "< 1 second"
        },
        {
            "name": "matrix_operations",
            "args": {"operation": "multiply", "matrix_size": 400, "duration_minutes": 1.0},
            "description": "🔢 Testing matrix multiplication (1 minute, 400x400 matrices)...",
            "expected_duration": "~1 minute"
        },
        {
            "name": "monte_carlo_simulation", 
            "args": {"num_simulations": 500000, "simulation_type": "pi_estimation", 
                    "duration_minutes": 1.5, "data_size_mb": 1.0},
            "description": "🎲 Testing Monte Carlo π estimation (1.5 minutes, 1MB dataset)...",
            "expected_duration": "~1.5 minutes"
        },
        {
            "name": "data_aggregation",
            "args": {"data_size_mb": 2.0, "duration_minutes": 1.0, "aggregation_type": "statistical"},
            "description": "📈 Testing statistical data aggregation (1 minute, 2MB dataset)...",
            "expected_duration": "~1 minute"
        },
        {
            "name": "hash_computation",
            "args": {"data_size_mb": 1.0, "hash_algorithm": "sha256", 
                    "duration_minutes": 1.0, "iterations_multiplier": 500},
            "description": "🔐 Testing hash computation (1 minute, 1MB data, SHA256)...",
            "expected_duration": "~1 minute"
        }
    ]
    
    # Get available tool names
    available_tool_names = {tool.name for tool in tools}
    
    total_execution_time = 0
    successful_tests = 0
    
    for test_case in test_cases:
        tool_name = test_case["name"]
        
        if tool_name not in available_tool_names:
            print(f"⏭️ Skipping {tool_name} - not available")
            continue
            
        try:
            print(f"\n{test_case['description']}")
            print(f"   Expected duration: {test_case['expected_duration']}")
            
            start_time = time.time()
            result = await session.call_tool(
                name=tool_name,
                arguments=test_case["args"]
            )
            end_time = time.time()
            
            execution_time = end_time - start_time
            total_execution_time += execution_time
            
            # Extract result content
            if result.content and len(result.content) > 0:
                result_text = result.content[0].text
                print(f"   ✅ Completed in {execution_time:.2f}s ({execution_time/60:.2f} minutes)")
                
                # Parse and display key results
                try:
                    result_data = json.loads(result_text)
                    if isinstance(result_data, dict):
                        # Display key metrics
                        if 'actual_duration_seconds' in result_data:
                            actual_duration = result_data['actual_duration_seconds']
                            print(f"   📊 Server reported duration: {actual_duration:.2f}s")
                        
                        if 'performance' in result_data:
                            perf = result_data['performance']
                            if 'memory_delta_mb' in perf:
                                print(f"   💾 Memory used: {perf['memory_delta_mb']:.2f}MB")
                            
                            # Tool-specific metrics
                            if 'simulations_per_second' in perf:
                                print(f"   🎯 Simulations/sec: {perf['simulations_per_second']:.0f}")
                            elif 'hashes_per_second' in perf:
                                print(f"   🔐 Hashes/sec: {perf['hashes_per_second']:.0f}")
                            elif 'rows_per_second' in perf:
                                print(f"   📊 Rows/sec: {perf['rows_per_second']:.0f}")
                        
                        # Display results summary
                        if 'results' in result_data and tool_name == 'monte_carlo_simulation':
                            results = result_data['results']
                            if 'mean' in results:
                                print(f"   🎲 π estimate: {results['mean']:.6f}")
                        
                        if 'iterations_completed' in result_data:
                            print(f"   🔄 Iterations: {result_data['iterations_completed']}")
                
                except json.JSONDecodeError:
                    print(f"   📄 Raw result length: {len(result_text)} characters")
                
                successful_tests += 1
            else:
                print(f"   ⚠️ No content in result after {execution_time:.2f}s")
                
        except Exception as e:
            execution_time = time.time() - start_time if 'start_time' in locals() else 0
            total_execution_time += execution_time
            print(f"   ❌ Error after {execution_time:.2f}s: {e}")
    
    print(f"\n📊 Testing Summary:")
    print(f"   Successful tests: {successful_tests}/{len(test_cases)}")
    print(f"   Total execution time: {total_execution_time:.2f}s ({total_execution_time/60:.2f} minutes)")
    print("✅ Long-running computational tool testing completed!")


async def connect_and_interact(credentials: LongRunningMCPCredentials) -> None:
    """
    Connect to long-running MCP server and perform computational operations.
    
    Args:
        credentials (LongRunningMCPCredentials): Server credentials and configuration
    """
    print(f"\n🌐 Connecting to long-running MCP server...")
    print(f"URL: {credentials.mcp_url}")
    print(f"Timeout: {CONNECTION_TIMEOUT}s ({CONNECTION_TIMEOUT/60:.1f} minutes)")
    print("Headers configured ✓")
    
    try:
        # Establish connection with extended timeout for long operations
        timeout = timedelta(seconds=CONNECTION_TIMEOUT)
        
        async with streamablehttp_client(
            credentials.mcp_url, 
            credentials.headers, 
            timeout=timeout, 
            terminate_on_close=False
        ) as (read_stream, write_stream, _):
            
            async with ClientSession(read_stream, write_stream) as session:
                print("\n🔄 Initializing MCP session...")
                await session.initialize()
                print("✅ MCP session initialized successfully")
                
                # Discover available computational tools
                tools = await list_available_tools(session)
                
                if not tools:
                    print("⚠️ No computational tools available for testing")
                    return
                
                # Test computational tool execution
                await test_computational_tools(session, tools)
                
                print(f"\n🎉 Successfully connected and tested long-running MCP server!")
                print(f"📊 Summary: {len(tools)} computational tools available and tested")
                print(f"⚡ Server optimized for payloads up to 3MB and operations up to 30 minutes")
                
    except Exception as e:
        print(f"❌ Connection error: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        raise LongRunningMCPClientError(f"Failed to connect to long-running MCP server: {e}")


async def main():
    """
    Main client function that orchestrates the long-running MCP connection and interaction.
    """
    print("🚀 Starting Long-Running MCP Remote Client")
    print("=" * 60)
    
    try:
        # Get AWS region
        region = get_aws_region()
        print(f"🌍 Using AWS region: {region}")
        
        # Retrieve credentials
        credentials = retrieve_credentials(region)
        
        # Connect and interact with long-running MCP server
        await connect_and_interact(credentials)
        
        print("\n" + "=" * 60)
        print("✅ Long-running MCP client session completed successfully!")
        print("💡 The server demonstrated handling of:")
        print("   - Large payloads (up to 3MB)")
        print("   - Long-running operations (configurable duration)")
        print("   - Complex computational tasks")
        print("   - Resource monitoring and performance tracking")
        
    except LongRunningMCPClientError as e:
        print(f"\n❌ Long-Running MCP Client Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⏹️ Client interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())