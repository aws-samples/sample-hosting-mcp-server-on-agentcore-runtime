#!/usr/bin/env python3
"""
Payload Size Scaling Tests

Tests MCP server behavior with increasing payload sizes (0.5MB → 10MB).
"""

import asyncio
import json
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, Tuple
from urllib.parse import quote

import boto3
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Configuration
SSM_PARAMETER_NAME = '/long_running_mcp_server_baseline/runtime/agent_arn'
SECRETS_MANAGER_SECRET_NAME = 'long_running_mcp_server_baseline/cognito/credentials'
CONNECTION_TIMEOUT = 2400
AGENTCORE_BASE_URL = "https://bedrock-agentcore.{region}.amazonaws.com"


class Credentials:
    def __init__(self, agent_arn: str, bearer_token: str, region: str):
        self.agent_arn = agent_arn
        self.bearer_token = bearer_token
        self.region = region
        
    @property
    def mcp_url(self) -> str:
        encoded = quote(self.agent_arn, safe='')
        return f"{AGENTCORE_BASE_URL.format(region=self.region)}/runtimes/{encoded}/invocations?qualifier=DEFAULT"
    
    @property
    def headers(self) -> Dict[str, str]:
        return {"authorization": f"Bearer {self.bearer_token}", "Content-Type": "application/json"}


def get_credentials() -> Credentials:
    print("🔑 Retrieving credentials...")
    region = boto3.Session().region_name
    ssm = boto3.client('ssm', region_name=region)
    secrets = boto3.client('secretsmanager', region_name=region)
    
    agent_arn = ssm.get_parameter(Name=SSM_PARAMETER_NAME)['Parameter']['Value']
    secret = json.loads(secrets.get_secret_value(SecretId=SECRETS_MANAGER_SECRET_NAME)['SecretString'])
    
    print(f"✓ Region: {region}")
    return Credentials(agent_arn, secret['bearer_token'], region)


async def invoke_tool(credentials: Credentials, tool: str, args: Dict) -> Tuple[bool, float, str, Dict, str]:
    """Single MCP server invocation. Returns (success, elapsed, error, data, session_id)."""
    start = time.time()
    try:
        timeout_secs = max(CONNECTION_TIMEOUT, args.get('duration_minutes', 1.0) * 60 + 120)
        timeout = timedelta(seconds=timeout_secs)
        sse_read_timeout = timedelta(seconds=timeout_secs)
        async with streamablehttp_client(credentials.mcp_url, credentials.headers, timeout=timeout, sse_read_timeout=sse_read_timeout, terminate_on_close=False) as (r, w, get_session_id):
            async with ClientSession(r, w) as session:
                await session.initialize()
                session_id = get_session_id() or "unknown"
                result = await session.call_tool(name=tool, arguments=args)
                elapsed = time.time() - start
                if result.content and len(result.content) > 0:
                    try:
                        data = json.loads(result.content[0].text)
                        return True, elapsed, "", data, session_id
                    except json.JSONDecodeError:
                        return True, elapsed, "", {}, session_id
                return False, elapsed, "No content", {}, session_id
    except Exception as e:
        error = str(e)
        if "SSE stream" in error or "ReadTimeout" in error:
            error = "AgentCore streaming limit reached"
        return False, time.time() - start, error[:100], {}, "unknown"


async def payload_size_test(credentials: Credentials) -> Dict:
    """Test increasing payload sizes with data_aggregation tool."""
    print(f"\n{'='*60}")
    print("📦 PAYLOAD SIZE TEST (data_aggregation)")
    print(f"{'='*60}")
    print("Testing: 0.5MB → 1.0MB → 2.0MB → 3.0MB → 5.0MB → 10.0MB (fixed 1-min duration)")
    
    payload_sizes = [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]
    results = []
    
    for size in payload_sizes:
        print(f"\n   🔄 Testing {size}MB payload...", flush=True)
        
        args = {"data_size_mb": size, "duration_minutes": 1.0, "aggregation_type": "statistical"}
        success, elapsed, error, data, session_id = await invoke_tool(credentials, "data_aggregation", args)
        
        memory = data.get('performance', {}).get('memory_delta_mb', 0)
        rows = data.get('dataset_rows', 0)
        
        results.append({
            "payload_mb": size, "success": success, "time_seconds": elapsed,
            "memory_mb": memory, "rows": rows, "error": error, "session_id": session_id
        })
        
        if success:
            print(f"   ✅ {size}MB: {elapsed:.2f}s | Memory: {memory:.2f}MB | Rows: {rows} | Session: {session_id}")
        else:
            print(f"   ❌ {size}MB: Failed after {elapsed:.2f}s - {error} | Session: {session_id}")
    
    # Summary
    successful = [r for r in results if r["success"]]
    print(f"\n{'─'*60}")
    print("📊 PAYLOAD SIZE SUMMARY")
    print(f"{'─'*60}")
    print(f"   Successful: {len(successful)}/{len(results)}")
    if successful:
        print(f"   Max successful payload: {max(r['payload_mb'] for r in successful)}MB")
        print(f"\n   {'Payload':<10} {'Time (s)':<12} {'Memory (MB)':<12} {'Rows':<10}")
        print(f"   {'─'*44}")
        for r in successful:
            print(f"   {r['payload_mb']:<10} {r['time_seconds']:<12.2f} {r['memory_mb']:<12.2f} {r['rows']:<10}")
    
    return {"test_type": "Payload Size Test", "results": results, "successful": len(successful)}


async def main():
    print("🚀 Payload Size Scaling Tests")
    print("=" * 60)
    
    try:
        credentials = get_credentials()
        payload_result = await payload_size_test(credentials)
        
        # Overall Summary
        print(f"\n{'='*60}")
        print("📋 OVERALL SUMMARY")
        print(f"{'='*60}")
        print(f"   Payload Size Test: {payload_result['successful']}/{len(payload_result['results'])} successful")
        
        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"payload_duration_results_{timestamp}.json"
        with open(filename, 'w') as f:
            json.dump({"timestamp": datetime.now().isoformat(), "results": [payload_result]}, f, indent=2)
        
        # Save session IDs for CloudWatch correlation
        session_data = []
        for r in payload_result['results']:
            session_data.append({
                "test_type": "payload_size", "test_detail": f"{r['payload_mb']}MB payload",
                "session_id": r.get("session_id", "unknown"), "success": r["success"]
            })
        with open("session-id.json", 'w') as f:
            json.dump(session_data, f, indent=2)
        
        print(f"\n💾 Results saved to: {filename}")
        print(f"💾 Session IDs saved to: session-id.json")
        print("✅ Testing completed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
