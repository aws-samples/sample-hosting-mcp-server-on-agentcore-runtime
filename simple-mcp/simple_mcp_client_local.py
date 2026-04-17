#!/usr/bin/env python3
"""
Local MCP Client for Development and Testing

This client connects to a locally running MCP server for development,
testing, and demonstration purposes. It provides comprehensive tool
discovery, testing, and interactive capabilities.

Features:
- Connects to local MCP server (no authentication required)
- Comprehensive tool discovery with schema inspection
- Automated testing of all available tools
- Interactive mode for manual tool testing
- Performance monitoring and error handling
- Detailed logging and reporting

Usage:
    python my_mcp_client_local.py [--interactive] [--url URL] [--timeout SECONDS]
"""

import asyncio
import argparse
import json
import sys
import time
import traceback
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Configuration constants
DEFAULT_MCP_URL = "http://localhost:8000/mcp"
DEFAULT_TIMEOUT = 120  # seconds
DEFAULT_HEADERS = {"Content-Type": "application/json"}


class LocalMCPClient:
    """
    Local MCP client for development and testing.
    
    This client provides comprehensive functionality for interacting
    with a local MCP server including tool discovery, testing, and
    interactive operations.
    """
    
    def __init__(self, url: str = DEFAULT_MCP_URL, timeout: int = DEFAULT_TIMEOUT):
        self.url = url
        self.timeout = timedelta(seconds=timeout)
        self.headers = DEFAULT_HEADERS.copy()
        self.session: Optional[ClientSession] = None
        self.tools: List = []
        
    async def connect(self) -> bool:
        """
        Establish connection to the MCP server.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            print(f"🌐 Connecting to local MCP server...")
            print(f"URL: {self.url}")
            print(f"Timeout: {self.timeout.total_seconds()}s")
            
            self.client_context = streamablehttp_client(
                self.url, 
                self.headers, 
                timeout=self.timeout, 
                terminate_on_close=False
            )
            
            self.streams = await self.client_context.__aenter__()
            read_stream, write_stream, _ = self.streams
            
            self.session_context = ClientSession(read_stream, write_stream)
            self.session = await self.session_context.__aenter__()
            
            print("🔄 Initializing MCP session...")
            await self.session.initialize()
            print("✅ Connected successfully!")
            
            return True
            
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
    
    async def disconnect(self):
        """Clean up connections and resources."""
        try:
            if hasattr(self, 'session_context') and self.session_context:
                await self.session_context.__aexit__(None, None, None)
            if hasattr(self, 'client_context') and self.client_context:
                await self.client_context.__aexit__(None, None, None)
            print("🔌 Disconnected from MCP server")
        except Exception as e:
            print(f"⚠️ Error during disconnect: {e}")
    
    async def discover_tools(self) -> List:
        """
        Discover and analyze available MCP tools.
        
        Returns:
            List: Available tools with their metadata
        """
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
        
        print("\n🔍 Discovering available tools...")
        
        try:
            tool_result = await self.session.list_tools()
            self.tools = tool_result.tools
            
            print(f"\n📋 Available Tools ({len(self.tools)} found):")
            print("=" * 70)
            
            for i, tool in enumerate(self.tools, 1):
                print(f"\n{i}. 🔧 {tool.name}")
                print(f"   📝 Description: {tool.description}")
                
                # Display input schema details
                if hasattr(tool, 'inputSchema') and tool.inputSchema:
                    properties = tool.inputSchema.get('properties', {})
                    required = tool.inputSchema.get('required', [])
                    
                    if properties:
                        print(f"   📊 Parameters:")
                        for param_name, param_info in properties.items():
                            param_type = param_info.get('type', 'unknown')
                            param_desc = param_info.get('description', 'No description')
                            required_marker = " (required)" if param_name in required else " (optional)"
                            print(f"     • {param_name} ({param_type}){required_marker}: {param_desc}")
                    else:
                        print(f"   📊 Parameters: None")
                else:
                    print(f"   📊 Parameters: No schema available")
            
            return self.tools
            
        except Exception as e:
            print(f"❌ Error discovering tools: {e}")
            return []
    
    async def test_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, Any]:
        """
        Test a specific tool with given arguments.
        
        Args:
            tool_name: Name of the tool to test
            arguments: Arguments to pass to the tool
            
        Returns:
            Tuple of (success: bool, result: Any)
        """
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
        
        try:
            start_time = time.time()
            result = await self.session.call_tool(name=tool_name, arguments=arguments)
            end_time = time.time()
            
            execution_time = round((end_time - start_time) * 1000, 2)  # ms
            
            if result.content and len(result.content) > 0:
                result_data = result.content[0].text
                print(f"   ✅ Success ({execution_time}ms): {result_data}")
                return True, result_data
            else:
                print(f"   ⚠️ No content returned ({execution_time}ms)")
                return False, None
                
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return False, str(e)
    
    async def run_comprehensive_tests(self):
        """
        Run comprehensive tests for all available tools.
        """
        if not self.tools:
            print("⚠️ No tools available for testing")
            return
        
        print(f"\n🧪 Running Comprehensive Tool Tests")
        print("=" * 70)
        
        # Define comprehensive test cases
        test_cases = {
            "add_numbers": [
                {"a": 5, "b": 3},
                {"a": -2, "b": 7},
                {"a": 2.5, "b": 1.5}
            ],
            "multiply_numbers": [
                {"a": 4, "b": 7},
                {"a": -3, "b": 5},
                {"a": 2.5, "b": 4}
            ],
            "divide_numbers": [
                {"a": 10, "b": 2},
                {"a": 7, "b": 3},
                {"a": 15, "b": 4}
            ],
            "power_numbers": [
                {"base": 2, "exponent": 3},
                {"base": 5, "exponent": 2},
                {"base": 4, "exponent": 0.5}
            ],
            "greet_user": [
                {"name": "Alice"},
                {"name": "Bob", "language": "es"},
                {"name": "Charlie", "language": "fr"}
            ],
            "calculate_statistics": [
                {"numbers": [1, 2, 3, 4, 5]},
                {"numbers": [10, 20, 30, 40, 50]},
                {"numbers": [1.5, 2.5, 3.5, 4.5]}
            ],
            "format_text": [
                {"text": "hello world", "operation": "upper"},
                {"text": "HELLO WORLD", "operation": "title"},
                {"text": "  spaced text  ", "operation": "strip"}
            ],
            "get_server_info": [{}]
        }
        
        # Get available tool names
        available_tools = {tool.name for tool in self.tools}
        
        total_tests = 0
        passed_tests = 0
        
        for tool_name, test_list in test_cases.items():
            if tool_name not in available_tools:
                print(f"⏭️ Skipping {tool_name} - not available")
                continue
            
            print(f"\n🔧 Testing {tool_name}:")
            
            for i, test_args in enumerate(test_list, 1):
                total_tests += 1
                args_str = ", ".join(f"{k}={v}" for k, v in test_args.items())
                print(f"   Test {i}: {tool_name}({args_str})")
                
                success, result = await self.test_tool(tool_name, test_args)
                if success:
                    passed_tests += 1
        
        # Test summary
        print(f"\n📊 Test Summary:")
        print(f"   Total Tests: {total_tests}")
        print(f"   Passed: {passed_tests}")
        print(f"   Failed: {total_tests - passed_tests}")
        print(f"   Success Rate: {(passed_tests/total_tests*100):.1f}%" if total_tests > 0 else "   Success Rate: N/A")
    
    async def interactive_mode(self):
        """
        Run interactive mode for manual tool testing.
        """
        if not self.tools:
            print("⚠️ No tools available for interactive testing")
            return
        
        print(f"\n🎮 Interactive Mode")
        print("=" * 50)
        print("Commands:")
        print("  list - Show available tools")
        print("  test <tool_name> <json_args> - Test a tool")
        print("  info <tool_name> - Show tool information")
        print("  quit - Exit interactive mode")
        print()
        
        while True:
            try:
                command = input("mcp> ").strip()
                
                if not command:
                    continue
                
                if command == "quit":
                    break
                
                if command == "list":
                    print("\nAvailable tools:")
                    for tool in self.tools:
                        print(f"  • {tool.name} - {tool.description}")
                    continue
                
                parts = command.split(" ", 2)
                
                if parts[0] == "info" and len(parts) >= 2:
                    tool_name = parts[1]
                    tool = next((t for t in self.tools if t.name == tool_name), None)
                    if tool:
                        print(f"\n🔧 {tool.name}")
                        print(f"Description: {tool.description}")
                        if hasattr(tool, 'inputSchema') and tool.inputSchema:
                            print(f"Schema: {json.dumps(tool.inputSchema, indent=2)}")
                    else:
                        print(f"❌ Tool '{tool_name}' not found")
                    continue
                
                if parts[0] == "test" and len(parts) >= 3:
                    tool_name = parts[1]
                    try:
                        args = json.loads(parts[2])
                        print(f"\n🧪 Testing {tool_name}...")
                        await self.test_tool(tool_name, args)
                    except json.JSONDecodeError:
                        print("❌ Invalid JSON arguments")
                    except Exception as e:
                        print(f"❌ Error: {e}")
                    continue
                
                print("❌ Unknown command. Type 'quit' to exit.")
                
            except KeyboardInterrupt:
                print("\n👋 Exiting interactive mode...")
                break
            except Exception as e:
                print(f"❌ Error: {e}")


async def main():
    """
    Main function that orchestrates the local MCP client operations.
    """
    parser = argparse.ArgumentParser(description="Local MCP Client for Development and Testing")
    parser.add_argument("--url", default=DEFAULT_MCP_URL, help="MCP server URL")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Connection timeout in seconds")
    parser.add_argument("--interactive", action="store_true", help="Run in interactive mode")
    parser.add_argument("--test-only", action="store_true", help="Run tests only (no interactive mode)")
    
    args = parser.parse_args()
    
    print("🚀 Local MCP Client Starting")
    print("=" * 50)
    
    client = LocalMCPClient(url=args.url, timeout=args.timeout)
    
    try:
        # Connect to server
        if not await client.connect():
            sys.exit(1)
        
        # Discover tools
        tools = await client.discover_tools()
        if not tools:
            print("⚠️ No tools found on server")
            return
        
        # Run comprehensive tests
        await client.run_comprehensive_tests()
        
        # Interactive mode (unless test-only)
        if not args.test_only:
            if args.interactive:
                await client.interactive_mode()
            else:
                print(f"\n💡 Tip: Use --interactive flag for manual testing")
        
        print(f"\n✅ Local MCP client session completed!")
        
    except KeyboardInterrupt:
        print(f"\n⏹️ Client interrupted by user")
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        print("Full traceback:")
        traceback.print_exc()
        sys.exit(1)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
