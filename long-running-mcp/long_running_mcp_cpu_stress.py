#!/usr/bin/env python3
"""
CPU Stress Test for Long-Running MCP Server on AgentCore Runtime

Tests CPU-intensive workloads at increasing concurrency levels using:
- matrix_operations (NumPy-bound: matrix multiply, eigenvalues, SVD)
- hash_computation (pure Python CPU: SHA-256 iterative hashing)

Each concurrency level fires N identical requests simultaneously to stress
the runtime's CPU scheduling and container scaling.
"""

import asyncio
import json
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from urllib.parse import quote

import boto3
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SSM_PARAMETER_NAME = '/long_running_mcp_server/runtime/agent_arn'
SECRETS_MANAGER_SECRET_NAME = 'long_running_mcp_server/cognito/credentials'
CONNECTION_TIMEOUT = 600
AGENTCORE_BASE_URL = "https://bedrock-agentcore.{region}.amazonaws.com"

# Test configuration
DURATION_MINUTES = 5.0  # Each request runs for 5 minutes
CONCURRENCY_LEVELS = [1]

STRESS_TESTS = [
    {
        "name": "Matrix SVD (NumPy CPU - Heavy)",
        "tool": "matrix_operations",
        "args": {"operation": "svd", "matrix_size": 2000, "duration_minutes": DURATION_MINUTES},
    },
    {
        "name": "Hash Computation (Pure CPU - Heavy)",
        "tool": "hash_computation",
        "args": {"data_size_mb": 10.0, "hash_algorithm": "sha512", "duration_minutes": DURATION_MINUTES, "iterations_multiplier": 5000},
    },
]


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
    """Single MCP tool invocation. Returns (success, elapsed_seconds, error, response_data, session_id)."""
    start = time.time()
    try:
        timeout = timedelta(seconds=CONNECTION_TIMEOUT)
        sse_read_timeout = timedelta(seconds=CONNECTION_TIMEOUT)
        async with streamablehttp_client(credentials.mcp_url, credentials.headers, timeout=timeout, sse_read_timeout=sse_read_timeout, terminate_on_close=False) as (r, w, get_session_id):
            async with ClientSession(r, w) as session:
                await session.initialize()
                session_id = get_session_id() or "unknown"
                result = await session.call_tool(name=tool, arguments=args)
                elapsed = time.time() - start
                if result.content and len(result.content) > 0:
                    try:
                        return True, elapsed, "", json.loads(result.content[0].text), session_id
                    except json.JSONDecodeError:
                        return True, elapsed, "", {}, session_id
                return False, elapsed, "No content", {}, session_id
    except Exception as e:
        return False, time.time() - start, str(e)[:120], {}, "unknown"


async def run_concurrency_level(credentials: Credentials, tool: str, args: Dict, concurrency: int) -> List[Dict]:
    """Fire `concurrency` identical requests simultaneously and collect results."""
    tasks = [invoke_tool(credentials, tool, args) for _ in range(concurrency)]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    results = []
    for i, r in enumerate(raw):
        if isinstance(r, Exception):
            results.append({"request": i + 1, "success": False, "elapsed": 0, "error": str(r)[:120], "session_id": "unknown"})
        else:
            success, elapsed, error, data, session_id = r
            entry = {"request": i + 1, "success": success, "elapsed": round(elapsed, 2), "error": error, "session_id": session_id}
            if success:
                perf = data.get("performance", {})
                entry["iterations"] = data.get("iterations_completed") or data.get("total_hash_operations")
                entry["memory_delta_mb"] = round(perf.get("memory_delta_mb", 0), 2)
            results.append(entry)
    return results


def print_level_results(concurrency: int, results: List[Dict], wall_time: float):
    """Print results for one concurrency level."""
    ok = [r for r in results if r["success"]]
    fail = len(results) - len(ok)
    times = [r["elapsed"] for r in ok]

    print(f"\n   Concurrency={concurrency}  |  Wall time: {wall_time:.2f}s  |  ✅ {len(ok)}  ❌ {fail}")
    if times:
        print(f"   Response times — avg: {sum(times)/len(times):.2f}s  min: {min(times):.2f}s  max: {max(times):.2f}s")
        iters = [r.get("iterations") for r in ok if r.get("iterations")]
        if iters:
            print(f"   Iterations — avg: {sum(iters)//len(iters)}  min: {min(iters)}  max: {max(iters)}")
    for r in results:
        status = "✅" if r["success"] else "❌"
        extra = f"  iters={r.get('iterations','—')}  mem_delta={r.get('memory_delta_mb','—')}MB  session={r.get('session_id','—')}" if r["success"] else f"  {r['error']}"
        print(f"     {status} req#{r['request']}: {r['elapsed']}s{extra}")


async def run_stress_test(credentials: Credentials, test_config: Dict) -> Dict:
    """Run one stress test across all concurrency levels."""
    name = test_config["name"]
    tool = test_config["tool"]
    args = test_config["args"]

    print(f"\n{'='*60}")
    print(f"🔥 {name}")
    print(f"{'='*60}")
    print(f"   Tool: {tool}  |  Duration per request: {DURATION_MINUTES} min")
    print(f"   Concurrency levels: {CONCURRENCY_LEVELS}")

    all_levels = []
    for c in CONCURRENCY_LEVELS:
        print(f"\n   🔄 Launching {c} concurrent request(s)...", flush=True)
        wall_start = time.time()
        results = await run_concurrency_level(credentials, tool, args, c)
        wall_time = time.time() - wall_start
        print_level_results(c, results, wall_time)
        all_levels.append({"concurrency": c, "wall_time": round(wall_time, 2), "results": results})

    # Summary table
    print(f"\n{'─'*60}")
    print(f"📊 {name} — SUMMARY")
    print(f"{'─'*60}")
    print(f"   {'Concurrency':<14} {'Wall (s)':<10} {'Avg (s)':<10} {'OK/Total':<10} {'Avg Iters':<10}")
    print(f"   {'─'*54}")
    for lvl in all_levels:
        ok = [r for r in lvl["results"] if r["success"]]
        avg_t = sum(r["elapsed"] for r in ok) / len(ok) if ok else 0
        iters = [r.get("iterations", 0) for r in ok if r.get("iterations")]
        avg_i = sum(iters) // len(iters) if iters else "—"
        print(f"   {lvl['concurrency']:<14} {lvl['wall_time']:<10} {avg_t:<10.2f} {len(ok)}/{len(lvl['results']):<8} {avg_i}")

    return {"test_name": name, "tool": tool, "levels": all_levels}


async def main():
    print("🔥 CPU Stress Test for Long-Running MCP Server")
    print("=" * 60)

    try:
        credentials = get_credentials()
        all_results = []

        for test_config in STRESS_TESTS:
            result = await run_stress_test(credentials, test_config)
            all_results.append(result)

        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"cpu_stress_results_{timestamp}.json"
        with open(filename, 'w') as f:
            json.dump({"timestamp": datetime.now().isoformat(), "results": all_results}, f, indent=2)
        
        # Save session IDs for CloudWatch correlation
        session_data = []
        for result in all_results:
            for lvl in result["levels"]:
                for r in lvl["results"]:
                    session_data.append({
                        "test_name": result["test_name"], "concurrency": lvl["concurrency"],
                        "request": r["request"], "session_id": r.get("session_id", "unknown"),
                        "success": r["success"]
                    })
        with open("session-id.json", 'w') as f:
            json.dump(session_data, f, indent=2)
        
        print(f"\n💾 Results saved to: {filename}")
        print(f"💾 Session IDs saved to: session-id.json")
        print("✅ CPU stress testing completed!")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
