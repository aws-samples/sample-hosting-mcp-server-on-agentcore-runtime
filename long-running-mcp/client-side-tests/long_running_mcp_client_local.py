#!/usr/bin/env python3
"""
Local Client for Long-Running MCP Server

This client connects to a locally running long-running MCP server for development,
testing, and demonstration of computational tools with large payloads.

Features:
- Connects to local MCP server (no authentication required)
- Tests computational tools with configurable parameters
- Monitors execution time and resource usage
- Interactive mode for manual testing
- Comprehensive test suites for different payload sizes and durations

Usage:
    python long_running_mcp_client_local.py [--interactive] [--url URL] [--quick-test]
"""

import argparse
import asyncio
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
DEFAULT_TIMEOUT = 1800  # 30 minutes for long-running operations
DEFAULT_HEADERS = {"Content-Type": "application/json"}


class LongRunningMCPClient:
    """
    Local MCP client for testing long-running computational tools.
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
            print(f"🌐 Connecting to long-running MCP server...")
            print(f"URL: {self.url}")
            print(f"Timeout: {self.timeout.total_seconds()}s ({self.timeout.total_seconds()/60:.1f} minutes)")
            
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
        Discover and analyze available computational tools.
        
        Returns:
            List: Available tools with their metadata
        """
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
        
        print("\n🔍 Discovering available computational tools...")
        
        try:
            tool_result = await self.session.list_tools()
            self.tools = tool_result.tools
            
            print(f"\n📋 Available Computational Tools ({len(self.tools)} found):")
            print("=" * 80)
            
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
    
    async def test_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, Any, float]:
        """
        Test a specific tool with given arguments and measure execution time.
        
        Args:
            tool_name: Name of the tool to test
            arguments: Arguments to pass to the tool
            
        Returns:
            Tuple of (success: bool, result: Any, execution_time: float)
        """
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
        
        try:
            print(f"   🚀 Starting {tool_name}...")
            start_time = time.time()
            
            result = await self.session.call_tool(name=tool_name, arguments=arguments)
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            if result.content and len(result.content) > 0:
                result_data = result.content[0].text
                print(f"   ✅ Completed in {execution_time:.2f}s ({execution_time/60:.2f} minutes)")
                return True, result_data, execution_time
            else:
                print(f"   ⚠️ No content returned after {execution_time:.2f}s")
                return False, None, execution_time
                
        except Exception as e:
            end_time = time.time()
            execution_time = end_time - start_time if 'start_time' in locals() else 0
            print(f"   ❌ Error after {execution_time:.2f}s: {e}")
            return False, str(e), execution_time
    
    async def run_quick_tests(self):
        """
        Run quick tests for all available tools with minimal parameters.
        """
        if not self.tools:
            print("⚠️ No tools available for testing")
            return
        
        print(f"\n🧪 Running Quick Tests (30-second operations)")
        print("=" * 80)
        
        # Define quick test cases (30 seconds each)
        quick_test_cases = {
            "matrix_operations": [
                {"operation": "multiply", "matrix_size": 200, "duration_minutes": 0.5}
            ],
            "monte_carlo_simulation": [
                {"num_simulations": 100000, "simulation_type": "pi_estimation", 
                 "duration_minutes": 0.5, "data_size_mb": 0.5}
            ],
            "prime_factorization": [
                {"duration_minutes": 0.5, "number_size_digits": 12}
            ],
            "data_aggregation": [
                {"data_size_mb": 1.0, "duration_minutes": 0.5, "aggregation_type": "statistical"}
            ],
            "hash_computation": [
                {"data_size_mb": 0.5, "hash_algorithm": "sha256", 
                 "duration_minutes": 0.5, "iterations_multiplier": 100}
            ],
            "get_server_status": [{}]
        }
        
        # Get available tool names
        available_tools = {tool.name for tool in self.tools}
        
        total_tests = 0
        passed_tests = 0
        total_time = 0
        
        for tool_name, test_list in quick_test_cases.items():
            if tool_name not in available_tools:
                print(f"⏭️ Skipping {tool_name} - not available")
                continue
            
            print(f"\n🔧 Testing {tool_name}:")
            
            for i, test_args in enumerate(test_list, 1):
                total_tests += 1
                args_str = ", ".join(f"{k}={v}" for k, v in test_args.items())
                print(f"   Test {i}: {tool_name}({args_str})")
                
                success, result, exec_time = await self.test_tool(tool_name, test_args)
                total_time += exec_time
                
                if success:
                    passed_tests += 1
                    # Parse and display key results
                    try:
                        if isinstance(result, str):
                            result_data = json.loads(result)
                            if isinstance(result_data, dict):
                                # Display key metrics
                                if 'performance' in result_data:
                                    perf = result_data['performance']
                                    if 'memory_delta_mb' in perf:
                                        print(f"     Memory used: {perf['memory_delta_mb']:.2f}MB")
                                if 'actual_duration_seconds' in result_data:
                                    print(f"     Actual duration: {result_data['actual_duration_seconds']:.2f}s")
                    except:
                        pass  # Skip parsing if result format is unexpected
        
        # Test summary
        print(f"\n📊 Quick Test Summary:")
        print(f"   Total Tests: {total_tests}")
        print(f"   Passed: {passed_tests}")
        print(f"   Failed: {total_tests - passed_tests}")
        print(f"   Success Rate: {(passed_tests/total_tests*100):.1f}%" if total_tests > 0 else "   Success Rate: N/A")
        print(f"   Total Execution Time: {total_time:.2f}s ({total_time/60:.2f} minutes)")
    
    async def run_comprehensive_tests(self):
        """
        Run comprehensive tests with various payload sizes and durations.
        """
        if not self.tools:
            print("⚠️ No tools available for testing")
            return
        
        print(f"\n🧪 Running Comprehensive Tests (Various durations and payload sizes)")
        print("=" * 80)
        print("⚠️ This will take significant time - each test runs for its specified duration")
        
        # Define comprehensive test cases
        comprehensive_test_cases = {
            "matrix_operations": [
                {"operation": "multiply", "matrix_size": 500, "duration_minutes": 2.0},
                {"operation": "eigenvalues", "matrix_size": 300, "duration_minutes": 3.0}
            ],
            "monte_carlo_simulation": [
                {"num_simulations": 1000000, "simulation_type": "pi_estimation", 
                 "duration_minutes": 2.0, "data_size_mb": 2.0},
                {"num_simulations": 500000, "simulation_type": "portfolio", 
                 "duration_minutes": 3.0, "data_size_mb": 1.0}
            ],
            "data_aggregation": [
                {"data_size_mb": 3.0, "duration_minutes": 2.0, "aggregation_type": "statistical"},
                {"data_size_mb": 2.0, "duration_minutes": 3.0, "aggregation_type": "clustering"}
            ],
            "hash_computation": [
                {"data_size_mb": 2.0, "hash_algorithm": "sha256", 
                 "duration_minutes": 2.0, "iterations_multiplier": 1000}
            ]
        }
        
        # Get available tool names
        available_tools = {tool.name for tool in self.tools}
        
        total_tests = 0
        passed_tests = 0
        total_time = 0
        
        for tool_name, test_list in comprehensive_test_cases.items():
            if tool_name not in available_tools:
                print(f"⏭️ Skipping {tool_name} - not available")
                continue
            
            print(f"\n🔧 Testing {tool_name}:")
            
            for i, test_args in enumerate(test_list, 1):
                total_tests += 1
                duration_min = test_args.get('duration_minutes', 'unknown')
                print(f"   Test {i}: {tool_name} (target: {duration_min} minutes)")
                
                success, result, exec_time = await self.test_tool(tool_name, test_args)
                total_time += exec_time
                
                if success:
                    passed_tests += 1
                    # Display detailed results
                    try:
                        if isinstance(result, str):
                            result_data = json.loads(result)
                            if isinstance(result_data, dict):
                                print(f"     ✓ Target: {duration_min}min, Actual: {exec_time/60:.2f}min")
                                if 'performance' in result_data:
                                    perf = result_data['performance']
                                    if 'memory_delta_mb' in perf:
                                        print(f"     ✓ Memory used: {perf['memory_delta_mb']:.2f}MB")
                    except:
                        pass
        
        # Comprehensive test summary
        print(f"\n📊 Comprehensive Test Summary:")
        print(f"   Total Tests: {total_tests}")
        print(f"   Passed: {passed_tests}")
        print(f"   Failed: {total_tests - passed_tests}")
        print(f"   Success Rate: {(passed_tests/total_tests*100):.1f}%" if total_tests > 0 else "   Success Rate: N/A")
        print(f"   Total Execution Time: {total_time:.2f}s ({total_time/60:.2f} minutes)")
    
    async def interactive_mode(self):
        """
        Run interactive mode for manual tool testing.
        """
        if not self.tools:
            print("⚠️ No tools available for interactive testing")
            return
        
        print(f"\n🎮 Interactive Mode for Long-Running Operations")
        print("=" * 60)
        print("Commands:")
        print("  list - Show available tools")
        print("  test <tool_name> <json_args> - Test a tool")
        print("  info <tool_name> - Show tool information")
        print("  examples - Show example commands")
        print("  quit - Exit interactive mode")
        print()
        print("⚠️ Note: Operations may run for several minutes based on duration_minutes parameter")
        print()
        
        while True:
            try:
                command = input("long-running-mcp> ").strip()
                
                if not command:
                    continue
                
                if command == "quit":
                    break
                
                if command == "list":
                    print("\nAvailable computational tools:")
                    for tool in self.tools:
                        print(f"  • {tool.name} - {tool.description}")
                    continue
                
                if command == "examples":
                    print("\nExample commands:")
                    print('  test matrix_operations {"operation": "multiply", "matrix_size": 300, "duration_minutes": 1.0}')
                    print('  test monte_carlo_simulation {"num_simulations": 100000, "duration_minutes": 1.0, "data_size_mb": 1.0}')
                    print('  test data_aggregation {"data_size_mb": 2.0, "duration_minutes": 1.0, "aggregation_type": "statistical"}')
                    print('  test hash_computation {"data_size_mb": 1.0, "duration_minutes": 1.0, "iterations_multiplier": 500}')
                    print('  test get_server_status {}')
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
                        print("⏳ This may take several minutes depending on duration_minutes parameter...")
                        success, result, exec_time = await self.test_tool(tool_name, args)
                        
                        if success:
                            print(f"📊 Execution completed in {exec_time:.2f}s ({exec_time/60:.2f} minutes)")
                            # Try to parse and display key results
                            try:
                                if isinstance(result, str):
                                    result_data = json.loads(result)
                                    if isinstance(result_data, dict):
                                        print("Key results:")
                                        for key, value in result_data.items():
                                            if key in ['performance', 'results', 'actual_duration_seconds']:
                                                print(f"  {key}: {value}")
                            except:
                                print(f"Raw result: {result[:200]}...")
                        
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
    parser = argparse.ArgumentParser(description="Local Client for Long-Running MCP Server")
    parser.add_argument("--url", default=DEFAULT_MCP_URL, help="MCP server URL")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Connection timeout in seconds")
    parser.add_argument("--interactive", action="store_true", help="Run in interactive mode")
    parser.add_argument("--quick-test", action="store_true", help="Run quick tests only (30 seconds each)")
    parser.add_argument("--comprehensive", action="store_true", help="Run comprehensive tests (longer duration)")
    
    args = parser.parse_args()
    
    print("🚀 Long-Running MCP Local Client Starting")
    print("=" * 60)
    
    client = LongRunningMCPClient(url=args.url, timeout=args.timeout)
    
    try:
        # Connect to server
        if not await client.connect():
            sys.exit(1)
        
        # Discover tools
        tools = await client.discover_tools()
        if not tools:
            print("⚠️ No tools found on server")
            return
        
        # Run tests based on arguments
        if args.quick_test:
            await client.run_quick_tests()
        elif args.comprehensive:
            await client.run_comprehensive_tests()
        else:
            # Default: run quick tests
            await client.run_quick_tests()
        
        # Interactive mode
        if args.interactive:
            await client.interactive_mode()
        elif not args.quick_test and not args.comprehensive:
            print(f"\n💡 Tip: Use --interactive flag for manual testing")
            print(f"💡 Tip: Use --comprehensive flag for longer duration tests")
        
        print(f"\n✅ Long-running MCP client session completed!")
        
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