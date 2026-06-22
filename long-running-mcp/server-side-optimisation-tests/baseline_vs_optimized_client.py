#!/usr/bin/env python3
"""
Baseline vs Optimized Server-Side Comparison Test.

Tests the actual server-side optimization (lazy loading) by using the SAME
client strategy against both the baseline and optimized MCP server deployments.

Key principles:
- Identical client calling pattern for both servers (no concurrency tricks)
- Calls tools that actually trigger the lazy-loaded libraries (numpy, pandas, scipy)
- Measures cold-start latency (first request) separately from warm latency
- Produces an apples-to-apples comparison of server-side performance

Usage:
    # Full comparison (cold-start + warm requests)
    python baseline_vs_optimized_client.py

    # Quick test with fewer warm requests
    python baseline_vs_optimized_client.py --warm-requests 5

    # Test specific tool only
    python baseline_vs_optimized_client.py --tool matrix_operations

    # Skip cold-start test (servers already warm)
    python baseline_vs_optimized_client.py --skip-cold-start
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import boto3
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

SERVER_CONFIGS = {
    "baseline": {
        "ssm_param": "/long_running_mcp_server_baseline/runtime/agent_arn",
        "secret_name": "long_running_mcp_server_baseline/cognito/credentials",
    },
    "optimized": {
        "ssm_param": "/long_running_mcp_server_optimized/runtime/agent_arn",
        "secret_name": "long_running_mcp_server_optimized/cognito/credentials",
    },
}

# Tools that exercise the lazy-loaded libraries
TEST_TOOLS = {
    "long_running_analysis": {
        "args": {
            "duration_seconds": 30,
            "num_stages": 6,
        },
        "description": "Multi-stage analysis with streaming progress (optimized) vs silent (baseline)",
        "triggers_lazy_load": False,
        "demonstrates_streaming": True,
    },
    "monte_carlo_simulation": {
        "args": {
            "num_simulations": 100000,
            "simulation_type": "pi_estimation",
            "duration_minutes": 0.5,
            "data_size_mb": 0.5,
        },
        "description": "Triggers NumPy lazy load",
        "triggers_lazy_load": True,
        "demonstrates_streaming": False,
    },
    "matrix_operations": {
        "args": {"operation": "multiply", "matrix_size": 200, "duration_minutes": 0.5},
        "description": "Triggers NumPy lazy load",
        "triggers_lazy_load": True,
        "demonstrates_streaming": False,
    },
    "data_aggregation": {
        "args": {"data_size_mb": 1.0, "duration_minutes": 0.5, "aggregation_type": "statistical"},
        "description": "Triggers Pandas + NumPy lazy load",
        "triggers_lazy_load": True,
        "demonstrates_streaming": False,
    },
    "get_server_status": {
        "args": {},
        "description": "Lightweight status check (no heavy libs)",
        "triggers_lazy_load": False,
        "demonstrates_streaming": False,
    },
    "hash_computation": {
        "args": {
            "data_size_mb": 0.5,
            "hash_algorithm": "sha256",
            "duration_minutes": 0.5,
            "iterations_multiplier": 100,
        },
        "description": "CPU-bound, no heavy lib imports",
        "triggers_lazy_load": False,
        "demonstrates_streaming": False,
    },
}

REQUEST_TIMEOUT = 300  # 5 minutes


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RequestResult:
    """Result of a single tool call."""
    tool_name: str
    latency_ms: float
    success: bool
    error: Optional[str] = None
    response_summary: Optional[str] = None


@dataclass
class ServerTestResults:
    """Aggregated results for one server variant."""
    variant: str  # "baseline" or "optimized"
    cold_start_results: List[RequestResult] = field(default_factory=list)
    warm_results: List[RequestResult] = field(default_factory=list)

    @property
    def cold_start_latency_ms(self) -> Optional[float]:
        if self.cold_start_results:
            successful = [r.latency_ms for r in self.cold_start_results if r.success]
            return successful[0] if successful else None
        return None

    @property
    def warm_latencies_ms(self) -> List[float]:
        return [r.latency_ms for r in self.warm_results if r.success]

    @property
    def mean_warm_latency_ms(self) -> float:
        lats = self.warm_latencies_ms
        return sum(lats) / len(lats) if lats else 0.0

    @property
    def p50_warm_latency_ms(self) -> float:
        lats = sorted(self.warm_latencies_ms)
        if not lats:
            return 0.0
        return lats[len(lats) // 2]

    @property
    def success_rate(self) -> float:
        total = len(self.warm_results)
        if total == 0:
            return 0.0
        return sum(1 for r in self.warm_results if r.success) / total * 100


# ─────────────────────────────────────────────────────────────────────────────
# Credential retrieval
# ─────────────────────────────────────────────────────────────────────────────


def get_credentials(variant: str) -> Tuple[str, Dict[str, str], str]:
    """Get URL, headers, and region for the specified server variant."""
    config = SERVER_CONFIGS[variant]
    region = boto3.Session().region_name

    ssm = boto3.client("ssm", region_name=region)
    secrets = boto3.client("secretsmanager", region_name=region)

    agent_arn = ssm.get_parameter(Name=config["ssm_param"])["Parameter"]["Value"]
    secret = json.loads(
        secrets.get_secret_value(SecretId=config["secret_name"])["SecretString"]
    )

    encoded = quote(agent_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded}/invocations?qualifier=DEFAULT"
    headers = {
        "authorization": f"Bearer {secret['bearer_token']}",
        "Content-Type": "application/json",
    }

    return url, headers, region


# ─────────────────────────────────────────────────────────────────────────────
# Test execution (identical for both servers)
# ─────────────────────────────────────────────────────────────────────────────


async def call_tool(
    url: str, headers: Dict[str, str], tool_name: str, tool_args: Dict
) -> RequestResult:
    """
    Make a single MCP tool call. Identical logic for both baseline and optimized.

    Opens a fresh session per call to simulate real-world usage and ensure
    we measure the server's actual response time without session-reuse bias.
    """
    timeout = timedelta(seconds=REQUEST_TIMEOUT)
    start = time.perf_counter()

    try:
        async with streamablehttp_client(
            url, headers, timeout=timeout, sse_read_timeout=timeout, terminate_on_close=False
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(name=tool_name, arguments=tool_args)

                elapsed_ms = (time.perf_counter() - start) * 1000

                # Extract brief summary from response
                summary = None
                if result.content and len(result.content) > 0:
                    try:
                        data = json.loads(result.content[0].text)
                        if isinstance(data, dict):
                            # Pick a few key fields for summary
                            if "actual_duration_seconds" in data:
                                summary = f"server_duration={data['actual_duration_seconds']:.1f}s"
                            elif "status" in data:
                                summary = f"status={data['status']}"
                    except (json.JSONDecodeError, IndexError):
                        summary = f"raw_len={len(result.content[0].text)}"

                return RequestResult(
                    tool_name=tool_name,
                    latency_ms=round(elapsed_ms, 2),
                    success=True,
                    response_summary=summary,
                )

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return RequestResult(
            tool_name=tool_name,
            latency_ms=round(elapsed_ms, 2),
            success=False,
            error=str(e)[:200],
        )


async def run_test_suite(
    url: str,
    headers: Dict[str, str],
    variant: str,
    tool_name: str,
    tool_args: Dict,
    warm_requests: int,
    skip_cold_start: bool,
) -> ServerTestResults:
    """
    Run the full test suite against one server variant.

    Uses sequential requests with identical client logic — the only variable
    is which server endpoint we're hitting.
    """
    results = ServerTestResults(variant=variant)

    if not skip_cold_start:
        print(f"   🧊 Cold-start request (first call after deploy)...")
        cold_result = await call_tool(url, headers, tool_name, tool_args)
        results.cold_start_results.append(cold_result)
        if cold_result.success:
            print(f"      ✅ {cold_result.latency_ms:.0f}ms ({cold_result.response_summary})")
        else:
            print(f"      ❌ Failed after {cold_result.latency_ms:.0f}ms: {cold_result.error}")

    # Warm requests (sequential, identical pattern)
    print(f"   🔥 Warm requests ({warm_requests} sequential calls)...")
    for i in range(warm_requests):
        result = await call_tool(url, headers, tool_name, tool_args)
        results.warm_results.append(result)
        status = "✅" if result.success else "❌"
        print(f"      [{i+1}/{warm_requests}] {status} {result.latency_ms:.0f}ms", end="")
        if result.response_summary:
            print(f" ({result.response_summary})", end="")
        if result.error:
            print(f" ERROR: {result.error}", end="")
        print()

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Comparison report
# ─────────────────────────────────────────────────────────────────────────────


def print_comparison(
    baseline: ServerTestResults,
    optimized: ServerTestResults,
    tool_name: str,
    tool_info: Dict,
):
    """Print a clear side-by-side comparison."""

    def delta(base_val, opt_val):
        if base_val == 0:
            return "—"
        pct = ((opt_val - base_val) / base_val) * 100
        return f"{pct:+.1f}%"

    print(f"\n{'═' * 70}")
    print(f"  SERVER-SIDE COMPARISON: {tool_name}")
    print(f"  {tool_info['description']}")
    print(f"  Triggers lazy-loaded libs: {'YES' if tool_info['triggers_lazy_load'] else 'NO'}")
    print(f"{'═' * 70}")

    # Cold start comparison
    baseline_cold = baseline.cold_start_latency_ms
    optimized_cold = optimized.cold_start_latency_ms

    if baseline_cold is not None and optimized_cold is not None:
        print(f"\n  🧊 COLD-START LATENCY (first request after container start)")
        print(f"  ┌──────────────────┬──────────────────┬──────────────────┬──────────────┐")
        print(f"  │                  │ Baseline         │ Optimized        │ Δ Change     │")
        print(f"  ├──────────────────┼──────────────────┼──────────────────┼──────────────┤")
        print(f"  │ Cold-start (ms)  │ {baseline_cold:>14.0f}   │ {optimized_cold:>14.0f}   │ {delta(baseline_cold, optimized_cold):>12} │")
        print(f"  └──────────────────┴──────────────────┴──────────────────┴──────────────┘")

        if tool_info["triggers_lazy_load"]:
            saved_ms = baseline_cold - optimized_cold
            print(f"\n  💡 Lazy-loading saved {saved_ms:.0f}ms on cold start"
                  f" ({delta(baseline_cold, optimized_cold)} change)")
        else:
            print(f"\n  ℹ️  This tool does NOT trigger lazy-loaded libraries.")
            print(f"      Cold-start difference is from container overhead only.")

    # Warm latency comparison
    print(f"\n  🔥 WARM LATENCY (server already running, libraries loaded)")
    print(f"  ┌──────────────────┬──────────────────┬──────────────────┬──────────────┐")
    print(f"  │ Metric           │ Baseline         │ Optimized        │ Δ Change     │")
    print(f"  ├──────────────────┼──────────────────┼──────────────────┼──────────────┤")
    print(f"  │ Mean latency (ms)│ {baseline.mean_warm_latency_ms:>14.0f}   │ {optimized.mean_warm_latency_ms:>14.0f}   │ {delta(baseline.mean_warm_latency_ms, optimized.mean_warm_latency_ms):>12} │")
    print(f"  │ p50 latency (ms) │ {baseline.p50_warm_latency_ms:>14.0f}   │ {optimized.p50_warm_latency_ms:>14.0f}   │ {delta(baseline.p50_warm_latency_ms, optimized.p50_warm_latency_ms):>12} │")
    print(f"  │ Success rate     │ {baseline.success_rate:>13.1f}%  │ {optimized.success_rate:>13.1f}%  │              │")
    print(f"  └──────────────────┴──────────────────┴──────────────────┴──────────────┘")

    print(f"\n  📝 NOTE: Warm latency should be similar for both since the optimization")
    print(f"     is lazy-loading (only affects first use of each library).")
    if tool_info.get("demonstrates_streaming"):
        print(f"\n  📡 STREAMING: The optimized server sends progress notifications every ~5s")
        print(f"     during this tool. The baseline stays silent until completion.")
        print(f"     Total latency is similar, but time-to-first-feedback differs significantly.")
    print(f"{'═' * 70}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(
        description="Server-Side Optimization Test: Baseline vs Optimized (same client strategy)"
    )
    parser.add_argument(
        "--tool",
        choices=list(TEST_TOOLS.keys()),
        default="long_running_analysis",
        help="Which tool to test (default: long_running_analysis — demonstrates streaming)",
    )
    parser.add_argument(
        "--warm-requests",
        type=int,
        default=10,
        help="Number of warm (steady-state) requests per server (default: 10)",
    )
    parser.add_argument(
        "--skip-cold-start",
        action="store_true",
        help="Skip cold-start measurement (useful if servers are already warm)",
    )
    parser.add_argument(
        "--all-tools",
        action="store_true",
        help="Test all tools sequentially",
    )
    args = parser.parse_args()

    tools_to_test = list(TEST_TOOLS.keys()) if args.all_tools else [args.tool]

    print("🧪 Server-Side Optimization Comparison Test")
    print("=" * 60)
    print(f"   Strategy: IDENTICAL client for both servers (sequential, new session per call)")
    print(f"   Tools: {', '.join(tools_to_test)}")
    print(f"   Warm requests per server: {args.warm_requests}")
    print(f"   Cold-start test: {'skipped' if args.skip_cold_start else 'enabled'}")
    print()

    # Retrieve credentials for both servers
    print("🔑 Retrieving credentials...")
    try:
        baseline_url, baseline_headers, region = get_credentials("baseline")
        print(f"   ✓ Baseline server ready (region: {region})")
    except Exception as e:
        print(f"   ❌ Failed to get baseline credentials: {e}")
        sys.exit(1)

    try:
        optimized_url, optimized_headers, _ = get_credentials("optimized")
        print(f"   ✓ Optimized server ready")
    except Exception as e:
        print(f"   ❌ Failed to get optimized credentials: {e}")
        sys.exit(1)

    all_results = []

    for tool_name in tools_to_test:
        tool_info = TEST_TOOLS[tool_name]
        tool_args = tool_info["args"]

        print(f"\n{'─' * 60}")
        print(f"🔧 Testing tool: {tool_name}")
        print(f"   {tool_info['description']}")
        print(f"   Triggers lazy-loaded libs: {'YES' if tool_info['triggers_lazy_load'] else 'NO'}")
        print(f"{'─' * 60}")

        # Run baseline
        print(f"\n📦 BASELINE server:")
        baseline_results = await run_test_suite(
            baseline_url, baseline_headers, "baseline",
            tool_name, tool_args, args.warm_requests, args.skip_cold_start,
        )

        # Run optimized
        print(f"\n⚡ OPTIMIZED server:")
        optimized_results = await run_test_suite(
            optimized_url, optimized_headers, "optimized",
            tool_name, tool_args, args.warm_requests, args.skip_cold_start,
        )

        # Print comparison
        print_comparison(baseline_results, optimized_results, tool_name, tool_info)

        all_results.append({
            "tool": tool_name,
            "triggers_lazy_load": tool_info["triggers_lazy_load"],
            "demonstrates_streaming": tool_info.get("demonstrates_streaming", False),
            "baseline": {
                "cold_start_ms": baseline_results.cold_start_latency_ms,
                "mean_warm_ms": round(baseline_results.mean_warm_latency_ms, 2),
                "p50_warm_ms": round(baseline_results.p50_warm_latency_ms, 2),
                "success_rate": baseline_results.success_rate,
            },
            "optimized": {
                "cold_start_ms": optimized_results.cold_start_latency_ms,
                "mean_warm_ms": round(optimized_results.mean_warm_latency_ms, 2),
                "p50_warm_ms": round(optimized_results.p50_warm_latency_ms, 2),
                "success_rate": optimized_results.success_rate,
            },
        })

    # Save results
    output = {
        "timestamp": datetime.now().isoformat(),
        "region": region,
        "test_config": {
            "warm_requests": args.warm_requests,
            "cold_start_tested": not args.skip_cold_start,
            "client_strategy": "sequential, new session per call (identical for both)",
        },
        "results": all_results,
    }

    filename = f"server_side_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n💾 Results saved to: {filename}")

    # Final summary
    if len(all_results) > 1:
        print(f"\n{'═' * 70}")
        print(f"  OVERALL SUMMARY")
        print(f"{'═' * 70}")
        for r in all_results:
            cold_baseline = r["baseline"]["cold_start_ms"]
            cold_optimized = r["optimized"]["cold_start_ms"]
            if cold_baseline and cold_optimized:
                saved = cold_baseline - cold_optimized
                print(f"  {r['tool']:30s} cold-start saved: {saved:+.0f}ms "
                      f"(lazy-load: {'YES' if r['triggers_lazy_load'] else 'NO'})")
        print(f"{'═' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
