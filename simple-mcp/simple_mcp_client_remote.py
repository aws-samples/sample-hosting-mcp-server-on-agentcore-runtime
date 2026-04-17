#!/usr/bin/env python3
"""
MCP Client for Remote AgentCore Runtime

This client connects to an MCP server deployed on Amazon Bedrock AgentCore Runtime
and demonstrates tool discovery and execution capabilities.

Features:
- Retrieves credentials from AWS Secrets Manager and Parameter Store
- Connects to remote MCP server with JWT authentication
- Lists available tools and their schemas
- Tests tool execution with sample data
- Comprehensive error handling and logging

Requirements:
- AWS credentials configured
- MCP server deployed via deploy_simple_mcp_server_on_agentcore_runtime.py
- mcp library installed
"""

import asyncio
import json
import sys
import traceback
from datetime import timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import boto3
from boto3.session import Session
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Configuration constants
SSM_PARAMETER_NAME = '/mcp_server/runtime/agent_arn'
SECRETS_MANAGER_SECRET_NAME = 'mcp_server/cognito/credentials'
CONNECTION_TIMEOUT = 120  # seconds
AGENTCORE_BASE_URL = "https://bedrock-agentcore.{region}.amazonaws.com"


class MCPClientError(Exception):
    """Custom exception for MCP client errors."""
    pass


class MCPCredentials:
    """Container for MCP server credentials and configuration."""
    
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
        MCPClientError: If region cannot be determined
    """
    try:
        boto_session = Session()
        region = boto_session.region_name
        if not region:
            raise MCPClientError("AWS region not configured")
        return region
    except Exception as e:
        raise MCPClientError(f"Failed to get AWS region: {e}")


def retrieve_credentials(region: str) -> MCPCredentials:
    """
    Retrieve MCP server credentials from AWS services.
    
    Args:
        region (str): AWS region
        
    Returns:
        MCPCredentials: Container with all necessary credentials
        
    Raises:
        MCPClientError: If credential retrieval fails
    """
    print("🔑 Retrieving credentials from AWS...")
    
    try:
        # Get Agent ARN from Parameter Store
        ssm_client = boto3.client('ssm', region_name=region)
        agent_arn_response = ssm_client.get_parameter(Name=SSM_PARAMETER_NAME)
        agent_arn = agent_arn_response['Parameter']['Value']
        print(f"✓ Retrieved Agent ARN: {agent_arn}")
        
        # Get Cognito credentials from Secrets Manager
        secrets_client = boto3.client('secretsmanager', region_name=region)
        response = secrets_client.get_secret_value(SecretId=SECRETS_MANAGER_SECRET_NAME)
        secret_value = response['SecretString']
        parsed_secret = json.loads(secret_value)
        bearer_token = parsed_secret['bearer_token']
        print("✓ Retrieved bearer token from Secrets Manager")
        
        return MCPCredentials(agent_arn, bearer_token, region)
        
    except boto3.exceptions.Boto3Error as e:
        raise MCPClientError(f"AWS service error: {e}")
    except json.JSONDecodeError as e:
        raise MCPClientError(f"Invalid JSON in secrets: {e}")
    except KeyError as e:
        raise MCPClientError(f"Missing key in secrets: {e}")
    except Exception as e:
        raise MCPClientError(f"Unexpected error retrieving credentials: {e}")


async def list_available_tools(session: ClientSession) -> List:
    """
    List and display all available MCP tools.
    
    Args:
        session (ClientSession): Active MCP session
        
    Returns:
        List: Available tools
    """
    print("\n🔄 Discovering available tools...")
    
    try:
        tool_result = await session.list_tools()
        tools = tool_result.tools
        
        print(f"\n📋 Available MCP Tools ({len(tools)} found):")
        print("=" * 60)
        
        for tool in tools:
            print(f"🔧 {tool.name}")
            print(f"   Description: {tool.description}")
            
            # Display input schema if available
            if hasattr(tool, 'inputSchema') and tool.inputSchema:
                properties = tool.inputSchema.get('properties', {})
                if properties:
                    print(f"   Parameters: {list(properties.keys())}")
                    
                    # Show parameter details
                    for param_name, param_info in properties.items():
                        param_type = param_info.get('type', 'unknown')
                        param_desc = param_info.get('description', 'No description')
                        print(f"     - {param_name} ({param_type}): {param_desc}")
            print()
        
        return tools
        
    except Exception as e:
        print(f"❌ Error listing tools: {e}")
        return []


async def test_tool_execution(session: ClientSession, tools: List) -> None:
    """
    Test execution of available MCP tools with sample data.
    
    Args:
        session (ClientSession): Active MCP session
        tools (List): Available tools to test
    """
    print("\n🧪 Testing MCP Tool Execution:")
    print("=" * 60)
    
    # Define test cases for known tools
    test_cases = [
        {
            "name": "add_numbers",
            "args": {"a": 5, "b": 3},
            "description": "➕ Testing add_numbers(5, 3)..."
        },
        {
            "name": "multiply_numbers", 
            "args": {"a": 4, "b": 7},
            "description": "✖️ Testing multiply_numbers(4, 7)..."
        },
        {
            "name": "greet_user",
            "args": {"name": "Alice"},
            "description": "👋 Testing greet_user('Alice')..."
        }
    ]
    
    # Get available tool names
    available_tool_names = {tool.name for tool in tools}
    
    for test_case in test_cases:
        tool_name = test_case["name"]
        
        if tool_name not in available_tool_names:
            print(f"⏭️ Skipping {tool_name} - not available")
            continue
            
        try:
            print(f"\n{test_case['description']}")
            result = await session.call_tool(
                name=tool_name,
                arguments=test_case["args"]
            )
            
            # Extract result content
            if result.content and len(result.content) > 0:
                result_text = result.content[0].text
                print(f"   ✅ Result: {result_text}")
            else:
                print("   ⚠️ No content in result")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    print("\n✅ Tool testing completed!")


async def connect_and_interact(credentials: MCPCredentials) -> None:
    """
    Connect to MCP server and perform interactive operations.
    
    Args:
        credentials (MCPCredentials): Server credentials and configuration
    """
    print(f"\n🌐 Connecting to MCP server...")
    print(f"URL: {credentials.mcp_url}")
    print("Headers configured ✓")
    
    try:
        # Establish connection with timeout
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
                
                # Discover available tools
                tools = await list_available_tools(session)
                
                if not tools:
                    print("⚠️ No tools available for testing")
                    return
                
                # Test tool execution
                await test_tool_execution(session, tools)
                
                print(f"\n🎉 Successfully connected and tested MCP server!")
                print(f"📊 Summary: {len(tools)} tools available and tested")
                
    except Exception as e:
        print(f"❌ Connection error: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        raise MCPClientError(f"Failed to connect to MCP server: {e}")


async def main():
    """
    Main client function that orchestrates the MCP connection and interaction.
    """
    print("🚀 Starting MCP Remote Client")
    print("=" * 50)
    
    try:
        # Get AWS region
        region = get_aws_region()
        print(f"🌍 Using AWS region: {region}")
        
        # Retrieve credentials
        credentials = retrieve_credentials(region)
        
        # Connect and interact with MCP server
        await connect_and_interact(credentials)
        
        print("\n" + "=" * 50)
        print("✅ MCP client session completed successfully!")
        
    except MCPClientError as e:
        print(f"\n❌ MCP Client Error: {e}")
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
