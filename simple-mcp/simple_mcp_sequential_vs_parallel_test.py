#!/usr/bin/env python3
"""
Simple MCP Server Sequential vs Concurrent Comparison Test

This script runs the same operations first sequentially, then concurrently,
and provides comparative analysis of the results.

Concurrent requests are batched at 25 per batch to respect the AgentCore
Runtime InvokeAgentRuntime API rate limit of 25 TPS.
"""

import asyncio
import json
import math
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from urllib.parse import quote

import boto3
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Configuration
SSM_PARAMETER_NAME = '/mcp_server/runtime/agent_arn'
SECRETS_MANAGER_SECRET_NAME = 'mcp_server/cognito/credentials'
CONNECTION_TIMEOUT = 30
AGENTCORE_BASE_URL = "https://bedrock-agentcore.{region}.amazonaws.com"
MAX_CONCURRENT_BATCH = 25  # AgentCore InvokeAgentRuntime API rate limit


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


async def single_request(credentials: Credentials, test_id: str, max_retries: int = 5) -> Tuple[str, bool, float, str]:
    """Single MCP server invocation - list tools, with exponential backoff retry."""
    start = time.time()
    for attempt in range(max_retries + 1):
        try:
            timeout = timedelta(seconds=CONNECTION_TIMEOUT)
            async with streamablehttp_client(credentials.mcp_url, credentials.headers, timeout=timeout, terminate_on_close=False) as (r, w, _):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    await session.list_tools()
                    return test_id, True, time.time() - start, ""
        except Exception as e:
            err_str = str(e)
            retryable = "429" in err_str or "ConnectError" in type(e).__name__ or "nodename" in err_str
            if retryable and attempt < max_retries:
                wait = min(2 ** attempt + (asyncio.get_event_loop().time() % 1), 30)
                await asyncio.sleep(wait)
                continue
            return test_id, False, time.time() - start, err_str[:100]


def _compute_stats(results: List[Dict]) -> Dict:
    """Compute aggregate stats from a list of result dicts."""
    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful
    times = [r["time"] * 1000 for r in results if r["success"]]
    return {
        "total_requests": len(results),
        "successful": successful,
        "failed": failed,
        "avg_time_ms": sum(times) / len(times) if times else 0,
        "min_time_ms": min(times) if times else 0,
        "max_time_ms": max(times) if times else 0,
    }


async def run_sequential(credentials: Credentials, num_requests: int) -> Dict:
    """Run tests one after another."""
    print(f"\n{'='*60}")
    print(f"🔄 SEQUENTIAL TEST ({num_requests} requests)")
    print(f"{'='*60}")
    
    start = time.time()
    results = []
    
    for i in range(num_requests):
        print(f"   [{i+1}/{num_requests}]...", end=" ", flush=True)
        test_id, success, elapsed, error = await single_request(credentials, f"seq_{i+1}")
        results.append({"id": test_id, "success": success, "time": elapsed, "error": error})
        print(f"{'✅' if success else '❌'} {elapsed*1000:.1f}ms")
    
    total_time = time.time() - start
    stats = _compute_stats(results)
    
    print(f"\n   📊 Total: {total_time:.2f}s | Success: {stats['successful']}/{num_requests}")
    
    return {"mode": "Sequential", "total_time": total_time, **stats}


async def run_concurrent(credentials: Credentials, num_requests: int) -> Tuple[Dict, List[Dict]]:
    """Run tests concurrently in batches of MAX_CONCURRENT_BATCH to respect API rate limits."""
    num_batches = math.ceil(num_requests / MAX_CONCURRENT_BATCH)
    
    print(f"\n{'='*60}")
    print(f"⚡ CONCURRENT TEST ({num_requests} requests in {num_batches} batch(es) of ≤{MAX_CONCURRENT_BATCH})")
    print(f"{'='*60}")
    
    overall_start = time.time()
    all_results = []
    batch_summaries = []
    
    for batch_idx in range(num_batches):
        batch_start_idx = batch_idx * MAX_CONCURRENT_BATCH
        batch_size = min(MAX_CONCURRENT_BATCH, num_requests - batch_start_idx)
        
        print(f"\n   --- Batch {batch_idx+1}/{num_batches} ({batch_size} requests) ---")
        
        batch_start = time.time()
        tasks = [
            single_request(credentials, f"conc_{batch_start_idx + i + 1}")
            for i in range(batch_size)
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        batch_time = time.time() - batch_start
        
        batch_results = []
        for i, res in enumerate(raw_results):
            global_idx = batch_start_idx + i + 1
            if isinstance(res, Exception):
                batch_results.append({"id": f"conc_{global_idx}", "success": False, "time": 0, "error": str(res)[:100]})
            else:
                test_id, success, elapsed, error = res
                batch_results.append({"id": test_id, "success": success, "time": elapsed, "error": error})
        
        stats = _compute_stats(batch_results)
        print(f"   ✅ {stats['successful']} successful, ❌ {stats['failed']} failed in {batch_time:.2f}s")
        
        batch_summaries.append({
            "batch": batch_idx + 1,
            "batch_size": batch_size,
            "batch_time": batch_time,
            **stats,
        })
        
        all_results.extend(batch_results)
        
        # Wait 2s between batches to avoid rate limit overlap
        if batch_idx < num_batches - 1:
            print(f"   ⏳ Waiting 2s before next batch...")
            await asyncio.sleep(2)
    
    overall_time = time.time() - overall_start
    overall_stats = _compute_stats(all_results)
    
    overall = {"mode": "Concurrent (batched)", "total_time": overall_time, **overall_stats}
    return overall, batch_summaries


def print_comparison(seq: Dict, conc: Dict, batch_summaries: List[Dict]):
    """Print comparative analysis with per-batch breakdown."""
    time_saved = seq["total_time"] - conc["total_time"]
    
    # Per-batch summary
    print(f"\n{'='*70}")
    print("📦 CONCURRENT BATCH BREAKDOWN")
    print(f"{'='*70}")
    print(f"\n┌─────────┬───────┬────────────┬───────────┬─────────┬────────────────┬────────────────┬────────────────┐")
    print(f"│ Batch   │ Size  │ Time (s)   │ Success   │ Failed  │ Avg (ms)       │ Min (ms)       │ Max (ms)       │")
    print(f"├─────────┼───────┼────────────┼───────────┼─────────┼────────────────┼────────────────┼────────────────┤")
    for b in batch_summaries:
        print(f"│ {b['batch']:>7} │ {b['batch_size']:>5} │ {b['batch_time']:>10.2f} │ {b['successful']:>9} │ {b['failed']:>7} │ {b['avg_time_ms']:>14.2f} │ {b['min_time_ms']:>14.2f} │ {b['max_time_ms']:>14.2f} │")
    print(f"└─────────┴───────┴────────────┴───────────┴─────────┴────────────────┴────────────────┴────────────────┘")

    # Overall comparison
    print(f"\n{'='*70}")
    print("📊 COMPARISON: Sequential vs Concurrent (Batched)")
    print(f"{'='*70}")
    print(f"""
┌─────────────────────────┬──────────────────┬──────────────────┬──────────────┐
│ Metric                  │ Sequential       │ Concurrent       │ Delta        │
├─────────────────────────┼──────────────────┼──────────────────┼──────────────┤
│ Total Requests          │ {seq['total_requests']:>16} │ {conc['total_requests']:>16} │ {0:>12} │
│ Total Time (s)          │ {seq['total_time']:>16.2f} │ {conc['total_time']:>16.2f} │ {time_saved:>12.2f} │
│ Successful              │ {seq['successful']:>16} │ {conc['successful']:>16} │ {seq['successful'] - conc['successful']:>12} │
│ Failed                  │ {seq['failed']:>16} │ {conc['failed']:>16} │ {seq['failed'] - conc['failed']:>12} │
│ Avg Response Time (ms)  │ {seq['avg_time_ms']:>16.2f} │ {conc['avg_time_ms']:>16.2f} │ {seq['avg_time_ms'] - conc['avg_time_ms']:>12.2f} │
│ Min Response Time (ms)  │ {seq['min_time_ms']:>16.2f} │ {conc['min_time_ms']:>16.2f} │ {seq['min_time_ms'] - conc['min_time_ms']:>12.2f} │
│ Max Response Time (ms)  │ {seq['max_time_ms']:>16.2f} │ {conc['max_time_ms']:>16.2f} │ {seq['max_time_ms'] - conc['max_time_ms']:>12.2f} │
│ Batches Used            │ {'1 (N/A)':>16} │ {len(batch_summaries):>16} │              │
└─────────────────────────┴──────────────────┴──────────────────┴──────────────┘

📈 Analysis:
   • Both modes made {seq['total_requests']} MCP server invocations
   • Concurrent ran in {len(batch_summaries)} batch(es) of ≤{MAX_CONCURRENT_BATCH} to respect 25 TPS API rate limit
   • Concurrent execution saved {time_saved:.2f}s
   • Time efficiency gain: {(time_saved/seq['total_time'])*100:.1f}%
""")


async def main():
    print("🚀 Simple MCP Server: Sequential vs Concurrent Comparison")
    print("=" * 60)
    
    # Ask user for iteration count
    try:
        num_tests = int(input("Enter number of iterations to execute: "))
        if num_tests < 1:
            print("❌ Number of iterations must be at least 1.")
            return
    except ValueError:
        print("❌ Invalid input. Please enter a positive integer.")
        return
    
    print(f"✓ Running {num_tests} iterations (concurrent batches of ≤{MAX_CONCURRENT_BATCH})")
    
    try:
        credentials = get_credentials()
        
        # Run sequential test
        seq_result = await run_sequential(credentials, num_tests)
        
        # Run concurrent test (batched)
        conc_result, batch_summaries = await run_concurrent(credentials, num_tests)
        
        # Print comparison with batch breakdown
        print_comparison(seq_result, conc_result, batch_summaries)
        
        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"simple_mcp_comparison_results_{timestamp}.json"
        with open(filename, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "num_tests": num_tests,
                "max_concurrent_batch": MAX_CONCURRENT_BATCH,
                "sequential": seq_result,
                "concurrent": conc_result,
                "batch_summaries": batch_summaries,
                "summary": {
                    "time_saved": seq_result["total_time"] - conc_result["total_time"],
                    "speedup": seq_result["total_time"] / conc_result["total_time"] if conc_result["total_time"] > 0 else 0
                }
            }, f, indent=2)
        
        print(f"💾 Results saved to: {filename}")
        print("✅ Comparison testing completed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
