#!/usr/bin/env python3
"""
Long-Running MCP Server for Amazon Bedrock AgentCore Runtime

This server implements computational tools that handle large payloads (up to 3MB)
and long-running operations (30 seconds to 30 minutes) for scalability testing.

Features:
- Large payload processing (up to 3MB JSON data)
- Configurable execution times (30s to 30min)
- Complex computational tasks and simulations
- Memory-efficient data processing
- Comprehensive progress tracking and monitoring
- Resource usage monitoring

Tools:
- matrix_operations: Large matrix computations (multiply, eigenvalues, SVD, inverse)
- monte_carlo_simulation: Configurable Monte Carlo simulations (pi estimation, portfolio, integration)
- prime_factorization: Large number prime factorization
- data_aggregation: Process and aggregate large datasets (statistical, groupby, clustering)
- hash_computation: Compute hashes with configurable iterations (SHA-256, SHA-512, MD5)
- get_server_status: Server health and resource monitoring
"""

import hashlib
import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Union

import psutil
# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Import scientific libraries with fallbacks
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    logger.warning("NumPy not available - matrix operations will be limited")
    HAS_NUMPY = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    logger.warning("Pandas not available - data aggregation will be limited")
    HAS_PANDAS = False

try:
    from scipy import stats
    HAS_SCIPY = True
except ImportError:
    logger.warning("SciPy not available - statistical functions will be limited")
    HAS_SCIPY = False

try:
    from sklearn.cluster import KMeans
    HAS_SKLEARN = True
except ImportError:
    logger.warning("Scikit-learn not available - clustering will be limited")
    HAS_SKLEARN = False
from mcp.server.fastmcp import FastMCP

# Server configuration
SERVER_HOST = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8000"))
DEBUG_MODE = os.getenv("MCP_DEBUG", "false").lower() == "true"

# Initialize FastMCP server
mcp = FastMCP(
    host=SERVER_HOST,
    stateless_http=True,
    debug=DEBUG_MODE
)

# Server metadata
SERVER_INFO = {
    "name": "Long-Running MCP Server",
    "version": "1.0.0", 
    "description": "Handles large payloads and long-running computational tasks",
    "author": "AWS Bedrock AgentCore Demo",
    "startup_time": datetime.now().isoformat(),
    "max_payload_mb": 10,
    "max_duration_minutes": 30
}


class ProgressTracker:
    """Tracks progress of long-running operations."""
    
    def __init__(self, total_steps: int, operation_name: str):
        self.total_steps = total_steps
        self.current_step = 0
        self.operation_name = operation_name
        self.start_time = time.time()
        self.last_log_time = self.start_time
        
    def update(self, steps: int = 1):
        """Update progress and log if significant time has passed."""
        self.current_step += steps
        current_time = time.time()
        
        # Log progress every 10 seconds or at completion
        if (current_time - self.last_log_time >= 10) or (self.current_step >= self.total_steps):
            progress_pct = (self.current_step / self.total_steps) * 100
            elapsed = current_time - self.start_time
            
            if self.current_step < self.total_steps:
                eta = (elapsed / self.current_step) * (self.total_steps - self.current_step)
                logger.info(f"{self.operation_name}: {progress_pct:.1f}% complete, ETA: {eta:.1f}s")
            else:
                logger.info(f"{self.operation_name}: 100% complete in {elapsed:.1f}s")
            
            self.last_log_time = current_time


def get_system_resources() -> Dict[str, float]:
    """Get current system resource usage."""
    process = psutil.Process()
    return {
        "cpu_percent": process.cpu_percent(),
        "memory_mb": process.memory_info().rss / 1024 / 1024,
        "memory_percent": process.memory_percent()
    }


def validate_duration(duration_minutes: float) -> float:
    """Validate and clamp duration to acceptable range."""
    if duration_minutes < 0.5:
        logger.warning(f"Duration {duration_minutes} too short, using 0.5 minutes")
        return 0.5
    elif duration_minutes > 30:
        logger.warning(f"Duration {duration_minutes} too long, using 30 minutes")
        return 30
    return duration_minutes


def generate_large_dataset(size_mb: float) -> List[Dict[str, Any]]:
    """Generate a large dataset of specified size in MB."""
    target_bytes = int(size_mb * 1024 * 1024)
    data = []
    estimated_size = 0
    
    logger.info(f"Generating {size_mb}MB dataset...")
    
    while estimated_size < target_bytes:
        record = {
            "id": len(data),
            "timestamp": datetime.now().isoformat(),
            "value": random.uniform(0, 1000),
            "category": random.choice(["A", "B", "C", "D", "E"]),
            "metadata": {
                "source": f"generator_{random.randint(1, 100)}",
                "quality": random.uniform(0.5, 1.0),
                "tags": [f"tag_{i}" for i in range(random.randint(1, 5))]
            },
            "measurements": [random.uniform(0, 100) for _ in range(10)]
        }
        data.append(record)
        # Estimate size per record instead of serializing entire list each time
        estimated_size += len(json.dumps(record).encode('utf-8')) + 2  # +2 for comma and spacing
        
        if len(data) % 1000 == 0:
            logger.info(f"Generated {len(data)} records, {estimated_size/1024/1024:.2f}MB")
    
    logger.info(f"Dataset complete: {len(data)} records, {estimated_size/1024/1024:.2f}MB")
    return data


def _calculate_mean(values: List[float]) -> float:
    """Calculate mean with fallback for missing NumPy."""
    return sum(values) / len(values) if values else 0.0


def _calculate_std(values: List[float]) -> float:
    """Calculate standard deviation with fallback for missing NumPy."""
    if not values:
        return 0.0
    mean = _calculate_mean(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5


@mcp.tool()
def matrix_operations(
    operation: str = "multiply",
    matrix_size: int = 500,
    duration_minutes: float = 5.0
) -> Dict[str, Any]:
    """
    Perform large matrix operations with configurable execution time.
    
    Args:
        operation: Type of operation ("multiply", "eigenvalues", "svd", "inverse")
        matrix_size: Size of square matrices (e.g., 1000 = 1000x1000 matrix)
        duration_minutes: Target execution time in minutes
        
    Returns:
        Dictionary with operation results and performance metrics
    """
    try:
        if not HAS_NUMPY:
            return {
                "error": "NumPy not available - matrix operations require NumPy",
                "operation": operation,
                "matrix_size": matrix_size,
                "fallback_used": True
            }
        
        duration_minutes = validate_duration(duration_minutes)
        target_duration = duration_minutes * 60  # Convert to seconds
        
        logger.info(f"Starting matrix {operation} with {matrix_size}x{matrix_size} matrices")
        logger.info(f"Target duration: {duration_minutes} minutes")
        
        start_time = time.time()
        start_resources = get_system_resources()
        
        # Generate large matrices
        logger.info("Generating matrices...")
        np.random.seed(42)  # For reproducible results
        matrix_a = np.random.rand(matrix_size, matrix_size)
        matrix_b = np.random.rand(matrix_size, matrix_size)
        
        result_data = {}
        iterations = 0
        
        # Perform operations until target duration is reached
        while (time.time() - start_time) < target_duration:
            iterations += 1
            
            if operation == "multiply":
                result = np.dot(matrix_a, matrix_b)
                result_data["determinant"] = float(np.linalg.det(result[:10, :10]))  # Small sample
                
            elif operation == "eigenvalues":
                # Use smaller matrix for eigenvalues to avoid excessive computation
                sample_size = min(matrix_size, 200)
                sample_matrix = matrix_a[:sample_size, :sample_size]
                eigenvals = np.linalg.eigvals(sample_matrix)
                result_data["max_eigenvalue"] = float(np.max(np.real(eigenvals)))
                result_data["min_eigenvalue"] = float(np.min(np.real(eigenvals)))
                
            elif operation == "svd":
                # SVD on smaller matrix
                sample_size = min(matrix_size, 300)
                sample_matrix = matrix_a[:sample_size, :sample_size]
                u, s, vt = np.linalg.svd(sample_matrix)
                result_data["largest_singular_value"] = float(s[0])
                result_data["smallest_singular_value"] = float(s[-1])
                
            elif operation == "inverse":
                # Add small identity to ensure invertibility
                regularized = matrix_a + 0.01 * np.eye(matrix_size)
                try:
                    inv_matrix = np.linalg.inv(regularized)
                    result_data["inverse_norm"] = float(np.linalg.norm(inv_matrix))
                except np.linalg.LinAlgError:
                    result_data["error"] = "Matrix not invertible"
            
            # Log progress every 30 seconds
            elapsed = time.time() - start_time
            if elapsed > 0 and int(elapsed) % 30 == 0:
                progress = (elapsed / target_duration) * 100
                logger.info(f"Matrix {operation}: {progress:.1f}% complete, iteration {iterations}")
        
        end_time = time.time()
        end_resources = get_system_resources()
        actual_duration = end_time - start_time
        
        return {
            "operation": operation,
            "matrix_size": matrix_size,
            "iterations_completed": iterations,
            "target_duration_minutes": duration_minutes,
            "actual_duration_seconds": round(actual_duration, 2),
            "result_data": result_data,
            "performance": {
                "start_memory_mb": start_resources["memory_mb"],
                "end_memory_mb": end_resources["memory_mb"],
                "memory_delta_mb": end_resources["memory_mb"] - start_resources["memory_mb"],
                "avg_cpu_percent": end_resources["cpu_percent"]
            }
        }
        
    except Exception as e:
        logger.error(f"Error in matrix_operations: {e}")
        raise ValueError(f"Matrix operation failed: {e}")


@mcp.tool()
def monte_carlo_simulation(
    num_simulations: int = 1000000,
    simulation_type: str = "pi_estimation",
    duration_minutes: float = 5.0,
    data_size_mb: float = 1.0
) -> Dict[str, Any]:
    """
    Run Monte Carlo simulations with large datasets.
    
    Args:
        num_simulations: Number of simulation iterations
        simulation_type: Type of simulation ("pi_estimation", "portfolio", "integration")
        duration_minutes: Target execution time in minutes
        data_size_mb: Size of dataset to generate for simulation
        
    Returns:
        Dictionary with simulation results and statistics
    """
    try:
        duration_minutes = validate_duration(duration_minutes)
        target_duration = duration_minutes * 60
        
        logger.info(f"Starting Monte Carlo {simulation_type} simulation")
        logger.info(f"Target: {num_simulations} simulations in {duration_minutes} minutes")
        
        start_time = time.time()
        start_resources = get_system_resources()
        
        # Generate large dataset if needed
        if data_size_mb > 0:
            dataset = generate_large_dataset(data_size_mb)
            logger.info(f"Generated dataset with {len(dataset)} records")
        
        results = []
        completed_simulations = 0
        progress_tracker = ProgressTracker(num_simulations, f"Monte Carlo {simulation_type}")
        
        if HAS_NUMPY:
            np.random.seed(42)
        else:
            random.seed(42)
        
        while (time.time() - start_time) < target_duration and completed_simulations < num_simulations:
            batch_size = min(10000, num_simulations - completed_simulations)
            
            if simulation_type == "pi_estimation":
                # Estimate π using random points in unit circle
                if HAS_NUMPY:
                    x = np.random.uniform(-1, 1, batch_size)
                    y = np.random.uniform(-1, 1, batch_size)
                    inside_circle = (x**2 + y**2) <= 1
                    pi_estimate = 4 * np.sum(inside_circle) / batch_size
                else:
                    # Fallback without NumPy
                    inside_count = 0
                    for _ in range(batch_size):
                        x = random.uniform(-1, 1)
                        y = random.uniform(-1, 1)
                        if x**2 + y**2 <= 1:
                            inside_count += 1
                    pi_estimate = 4 * inside_count / batch_size
                results.append(pi_estimate)
                
            elif simulation_type == "portfolio":
                # Portfolio value simulation
                if HAS_NUMPY:
                    returns = np.random.normal(0.001, 0.02, batch_size)  # Daily returns
                    portfolio_values = 100000 * np.cumprod(1 + returns)  # Starting with $100k
                    final_value = portfolio_values[-1]
                else:
                    # Fallback without NumPy
                    portfolio_value = 100000
                    for _ in range(batch_size):
                        daily_return = random.gauss(0.001, 0.02)
                        portfolio_value *= (1 + daily_return)
                    final_value = portfolio_value
                results.append(final_value)
                
            elif simulation_type == "integration":
                # Monte Carlo integration of x^2 from 0 to 1
                if HAS_NUMPY:
                    x = np.random.uniform(0, 1, batch_size)
                    y = x**2
                    integral_estimate = np.mean(y)
                else:
                    # Fallback without NumPy
                    y_values = []
                    for _ in range(batch_size):
                        x = random.uniform(0, 1)
                        y_values.append(x**2)
                    integral_estimate = fallback_mean(y_values)
                results.append(integral_estimate)
            
            completed_simulations += batch_size
            progress_tracker.update(batch_size)
        
        end_time = time.time()
        end_resources = get_system_resources()
        actual_duration = end_time - start_time
        
        # Calculate statistics
        if results:
            if HAS_NUMPY:
                mean_result = np.mean(results)
                std_result = np.std(results)
                min_result = np.min(results)
                max_result = np.max(results)
            else:
                mean_result = fallback_mean(results)
                std_result = fallback_std(results)
                min_result = min(results)
                max_result = max(results)
        else:
            mean_result = std_result = min_result = max_result = 0
        
        return {
            "simulation_type": simulation_type,
            "completed_simulations": completed_simulations,
            "target_simulations": num_simulations,
            "completion_rate": (completed_simulations / num_simulations) * 100,
            "target_duration_minutes": duration_minutes,
            "actual_duration_seconds": round(actual_duration, 2),
            "dataset_size_mb": data_size_mb,
            "results": {
                "mean": float(mean_result),
                "std_dev": float(std_result),
                "min": float(min_result),
                "max": float(max_result),
                "sample_count": len(results)
            },
            "performance": {
                "simulations_per_second": completed_simulations / actual_duration,
                "memory_delta_mb": end_resources["memory_mb"] - start_resources["memory_mb"]
            }
        }
        
    except Exception as e:
        logger.error(f"Error in monte_carlo_simulation: {e}")
        raise ValueError(f"Monte Carlo simulation failed: {e}")


@mcp.tool()
def prime_factorization(
    target_number: int = None,
    duration_minutes: float = 5.0,
    number_size_digits: int = 15
) -> Dict[str, Any]:
    """
    Perform prime factorization of large numbers.
    
    Args:
        target_number: Specific number to factorize (optional)
        duration_minutes: Target execution time in minutes
        number_size_digits: Size of random numbers to generate if target_number not provided
        
    Returns:
        Dictionary with factorization results
    """
    try:
        duration_minutes = validate_duration(duration_minutes)
        target_duration = duration_minutes * 60
        
        start_time = time.time()
        start_resources = get_system_resources()
        
        if target_number is None:
            # Generate a large number
            target_number = random.randint(10**(number_size_digits-1), 10**number_size_digits - 1)
        
        logger.info(f"Starting prime factorization of {target_number}")
        logger.info(f"Target duration: {duration_minutes} minutes")
        
        def trial_division(n):
            """Simple trial division factorization."""
            factors = []
            d = 2
            while d * d <= n and (time.time() - start_time) < target_duration:
                while n % d == 0:
                    factors.append(d)
                    n //= d
                d += 1
                
                # Log progress for very large numbers
                if d % 100000 == 0:
                    elapsed = time.time() - start_time
                    progress = (elapsed / target_duration) * 100
                    logger.info(f"Prime factorization: {progress:.1f}% time elapsed, testing divisor {d}")
            
            if n > 1:
                factors.append(n)
            return factors
        
        # Perform factorization
        factors = trial_division(target_number)
        
        end_time = time.time()
        end_resources = get_system_resources()
        actual_duration = end_time - start_time
        
        # Verify factorization
        product = 1
        for factor in factors:
            product *= factor
        
        is_complete = (product == target_number)
        
        return {
            "target_number": target_number,
            "factors_found": factors,
            "is_complete_factorization": is_complete,
            "largest_factor": max(factors) if factors else None,
            "num_factors": len(factors),
            "target_duration_minutes": duration_minutes,
            "actual_duration_seconds": round(actual_duration, 2),
            "verification": {
                "product_of_factors": product,
                "matches_target": is_complete
            },
            "performance": {
                "memory_delta_mb": end_resources["memory_mb"] - start_resources["memory_mb"]
            }
        }
        
    except Exception as e:
        logger.error(f"Error in prime_factorization: {e}")
        raise ValueError(f"Prime factorization failed: {e}")


@mcp.tool()
def data_aggregation(
    data_size_mb: float = 5.0,
    duration_minutes: float = 10.0,
    aggregation_type: str = "statistical"
) -> Dict[str, Any]:
    """
    Process and aggregate large datasets.
    
    Args:
        data_size_mb: Size of dataset to generate and process
        duration_minutes: Target execution time in minutes
        aggregation_type: Type of aggregation ("statistical", "groupby", "clustering")
        
    Returns:
        Dictionary with aggregation results
    """
    try:
        duration_minutes = validate_duration(duration_minutes)
        target_duration = duration_minutes * 60
        
        logger.info(f"Starting data aggregation: {aggregation_type}")
        logger.info(f"Dataset size: {data_size_mb}MB, Duration: {duration_minutes} minutes")
        
        start_time = time.time()
        start_resources = get_system_resources()
        
        # Generate large dataset
        dataset = generate_large_dataset(data_size_mb)
        
        if not HAS_PANDAS:
            # Fallback processing without Pandas
            logger.info(f"Processing {len(dataset)} records without Pandas")
            
            # Simple aggregations without Pandas
            values = [record['value'] for record in dataset]
            categories = [record['category'] for record in dataset]
            
            results = {
                "fallback_analysis": {
                    "total_records": len(dataset),
                    "mean_value": fallback_mean(values),
                    "std_value": fallback_std(values),
                    "min_value": min(values),
                    "max_value": max(values),
                    "unique_categories": len(set(categories))
                }
            }
            
            # Simulate processing time
            iterations = 0
            while (time.time() - start_time) < target_duration:
                iterations += 1
                # Simple processing to consume time
                for i, record in enumerate(dataset):
                    if i % 1000 == 0:
                        break
                
                elapsed = time.time() - start_time
                if elapsed > 0 and int(elapsed) % 30 == 0:
                    progress = (elapsed / target_duration) * 100
                    logger.info(f"Data processing (fallback): {progress:.1f}% complete, iteration {iterations}")
            
            end_time = time.time()
            end_resources = get_system_resources()
            actual_duration = end_time - start_time
            
            return {
                "aggregation_type": f"{aggregation_type}_fallback",
                "dataset_size_mb": data_size_mb,
                "dataset_rows": len(dataset),
                "dataset_columns": len(dataset[0].keys()) if dataset else 0,
                "iterations_completed": iterations,
                "target_duration_minutes": duration_minutes,
                "actual_duration_seconds": round(actual_duration, 2),
                "results": results,
                "fallback_used": True,
                "performance": {
                    "rows_per_second": (len(dataset) * iterations) / actual_duration,
                    "memory_delta_mb": end_resources["memory_mb"] - start_resources["memory_mb"]
                }
            }
        
        df = pd.DataFrame(dataset)
        logger.info(f"Created DataFrame with {len(df)} rows and {len(df.columns)} columns")
        
        results = {}
        iterations = 0
        
        while (time.time() - start_time) < target_duration:
            iterations += 1
            
            if aggregation_type == "statistical":
                # Comprehensive statistical analysis
                numeric_cols = ['value'] + [f'measurements_{i}' for i in range(10)]
                
                # Expand measurements column into separate columns
                measurements_df = pd.DataFrame(df['measurements'].tolist())
                measurements_df.columns = [f'measurements_{i}' for i in range(10)]
                analysis_df = pd.concat([df[['value']], measurements_df], axis=1)
                
                stats_result = {
                    "mean": analysis_df.mean().to_dict(),
                    "std": analysis_df.std().to_dict(),
                    "correlation_matrix": analysis_df.corr().to_dict(),
                    "quantiles": analysis_df.quantile([0.25, 0.5, 0.75]).to_dict()
                }
                results["statistical_analysis"] = stats_result
                
            elif aggregation_type == "groupby":
                # Group by operations
                grouped = df.groupby('category').agg({
                    'value': ['mean', 'std', 'count', 'min', 'max'],
                    'id': 'count'
                })
                results["groupby_analysis"] = grouped.to_dict()
                
            elif aggregation_type == "clustering":
                # K-means clustering on measurements
                if HAS_NUMPY and HAS_SKLEARN:
                    measurements_array = np.array(df['measurements'].tolist())
                    if len(measurements_array) > 100:  # Only cluster if enough data
                        kmeans = KMeans(n_clusters=5, random_state=42, n_init=10)
                        clusters = kmeans.fit_predict(measurements_array)
                        
                        results["clustering_analysis"] = {
                            "cluster_centers": kmeans.cluster_centers_.tolist(),
                            "cluster_counts": pd.Series(clusters).value_counts().to_dict(),
                            "inertia": float(kmeans.inertia_)
                        }
                else:
                    # Simple fallback clustering
                    measurements = df['measurements'].tolist()
                    results["clustering_analysis"] = {
                        "fallback_clustering": True,
                        "total_measurements": len(measurements),
                        "note": "Advanced clustering requires scikit-learn"
                    }
            
            # Log progress
            elapsed = time.time() - start_time
            if elapsed > 0 and int(elapsed) % 30 == 0:
                progress = (elapsed / target_duration) * 100
                logger.info(f"Data aggregation: {progress:.1f}% complete, iteration {iterations}")
        
        end_time = time.time()
        end_resources = get_system_resources()
        actual_duration = end_time - start_time
        
        return {
            "aggregation_type": aggregation_type,
            "dataset_size_mb": data_size_mb,
            "dataset_rows": len(df),
            "dataset_columns": len(df.columns),
            "iterations_completed": iterations,
            "target_duration_minutes": duration_minutes,
            "actual_duration_seconds": round(actual_duration, 2),
            "results": results,
            "performance": {
                "rows_per_second": (len(df) * iterations) / actual_duration,
                "memory_delta_mb": end_resources["memory_mb"] - start_resources["memory_mb"]
            }
        }
        
    except Exception as e:
        logger.error(f"Error in data_aggregation: {e}")
        raise ValueError(f"Data aggregation failed: {e}")


@mcp.tool()
def hash_computation(
    data_size_mb: float = 2.0,
    hash_algorithm: str = "sha256",
    duration_minutes: float = 5.0,
    iterations_multiplier: int = 1000
) -> Dict[str, Any]:
    """
    Compute hashes for large data with configurable iterations.
    
    Args:
        data_size_mb: Size of data to hash
        hash_algorithm: Hash algorithm ("sha256", "sha512", "md5")
        duration_minutes: Target execution time in minutes
        iterations_multiplier: Multiplier for hash iterations
        
    Returns:
        Dictionary with hash computation results
    """
    try:
        duration_minutes = validate_duration(duration_minutes)
        target_duration = duration_minutes * 60
        
        logger.info(f"Starting hash computation: {hash_algorithm}")
        logger.info(f"Data size: {data_size_mb}MB, Duration: {duration_minutes} minutes")
        
        start_time = time.time()
        start_resources = get_system_resources()
        
        # Generate data to hash
        data_bytes = os.urandom(int(data_size_mb * 1024 * 1024))
        logger.info(f"Generated {len(data_bytes)} bytes of random data")
        
        hash_results = []
        iterations = 0
        
        # Select hash function
        if hash_algorithm == "sha256":
            hash_func = hashlib.sha256
        elif hash_algorithm == "sha512":
            hash_func = hashlib.sha512
        elif hash_algorithm == "md5":
            hash_func = hashlib.md5
        else:
            raise ValueError(f"Unsupported hash algorithm: {hash_algorithm}")
        
        while (time.time() - start_time) < target_duration:
            # Perform multiple hash iterations
            current_data = data_bytes
            
            for i in range(iterations_multiplier):
                hasher = hash_func()
                hasher.update(current_data)
                hash_result = hasher.hexdigest()
                current_data = hash_result.encode('utf-8')
            
            hash_results.append(hash_result)
            iterations += 1
            
            # Log progress
            elapsed = time.time() - start_time
            if elapsed > 0 and int(elapsed) % 30 == 0:
                progress = (elapsed / target_duration) * 100
                hashes_per_sec = (iterations * iterations_multiplier) / elapsed
                logger.info(f"Hash computation: {progress:.1f}% complete, {hashes_per_sec:.1f} hashes/sec")
        
        end_time = time.time()
        end_resources = get_system_resources()
        actual_duration = end_time - start_time
        
        total_hashes = iterations * iterations_multiplier
        
        return {
            "hash_algorithm": hash_algorithm,
            "data_size_mb": data_size_mb,
            "iterations_multiplier": iterations_multiplier,
            "total_hash_operations": total_hashes,
            "final_hash": hash_results[-1] if hash_results else None,
            "unique_hashes": len(set(hash_results)),
            "target_duration_minutes": duration_minutes,
            "actual_duration_seconds": round(actual_duration, 2),
            "performance": {
                "hashes_per_second": total_hashes / actual_duration,
                "mb_processed_per_second": (data_size_mb * iterations) / actual_duration,
                "memory_delta_mb": end_resources["memory_mb"] - start_resources["memory_mb"]
            }
        }
        
    except Exception as e:
        logger.error(f"Error in hash_computation: {e}")
        raise ValueError(f"Hash computation failed: {e}")


@mcp.tool()
def long_running_analysis(
    duration_seconds: int = 30,
    num_stages: int = 6,
) -> Dict[str, Any]:
    """
    Multi-stage long-running analysis (baseline — no progress streaming).
    Runs silently until all stages complete, then returns the full result.

    Args:
        duration_seconds: Total target execution time in seconds (default: 30)
        num_stages: Number of processing stages to execute (default: 6)

    Returns:
        Dictionary with per-stage results, timing, and performance metrics
    """
    try:
        duration_seconds = max(10, min(duration_seconds, 300))  # Clamp 10s–5min
        num_stages = max(2, min(num_stages, 20))
        stage_duration = duration_seconds / num_stages

        logger.info(f"Starting long_running_analysis: {duration_seconds}s, {num_stages} stages")

        start_time = time.time()
        start_resources = get_system_resources()
        stage_results = []

        for stage_idx in range(num_stages):
            stage_name = f"stage_{stage_idx + 1}"
            stage_start = time.time()

            # Simulate computational work for this stage
            iterations = 0
            stage_result_value = 0.0
            while (time.time() - stage_start) < stage_duration:
                # CPU work: compute a running sum of random values
                batch = [random.random() for _ in range(10000)]
                stage_result_value += sum(batch)
                iterations += 1

            stage_elapsed = time.time() - stage_start

            stage_results.append({
                "stage": stage_name,
                "iterations": iterations,
                "computed_value": round(stage_result_value, 2),
                "duration_seconds": round(stage_elapsed, 2),
            })

            # Log progress (server-side only, no client notification)
            logger.info(f"[{stage_idx+1}/{num_stages}] {stage_name} complete: {iterations} iterations in {stage_elapsed:.1f}s")

        end_time = time.time()
        end_resources = get_system_resources()
        actual_duration = end_time - start_time

        total_iterations = sum(s["iterations"] for s in stage_results)

        return {
            "num_stages": num_stages,
            "target_duration_seconds": duration_seconds,
            "actual_duration_seconds": round(actual_duration, 2),
            "total_iterations": total_iterations,
            "stages": stage_results,
            "performance": {
                "iterations_per_second": total_iterations / actual_duration,
                "memory_delta_mb": end_resources["memory_mb"] - start_resources["memory_mb"],
                "avg_stage_duration_seconds": round(actual_duration / num_stages, 2),
            },
        }

    except Exception as e:
        logger.error(f"Error in long_running_analysis: {e}")
        raise ValueError(f"Long-running analysis failed: {e}")


@mcp.tool()
def get_server_status() -> Dict[str, Any]:
    """
    Get comprehensive server status and resource information.
    
    Returns:
        Dictionary with server status and system resources
    """
    try:
        current_time = datetime.now()
        resources = get_system_resources()
        
        # Get system information
        system_info = {
            "cpu_count": psutil.cpu_count(),
            "memory_total_gb": psutil.virtual_memory().total / (1024**3),
            "memory_available_gb": psutil.virtual_memory().available / (1024**3),
            "disk_usage_percent": psutil.disk_usage('/').percent
        }
        
        return {
            **SERVER_INFO,
            "current_time": current_time.isoformat(),
            "uptime_seconds": (current_time - datetime.fromisoformat(SERVER_INFO["startup_time"])).total_seconds(),
            "status": "running",
            "tools_available": 6,
            "current_resources": resources,
            "system_info": system_info
        }
        
    except Exception as e:
        logger.error(f"Error in get_server_status: {e}")
        raise ValueError(f"Failed to get server status: {e}")


def setup_server_logging():
    """Configure server logging and startup information."""
    logger.info("=" * 70)
    logger.info("🚀 Starting Long-Running MCP Server for AgentCore Runtime")
    logger.info(f"📊 Server: {SERVER_INFO['name']} v{SERVER_INFO['version']}")
    logger.info(f"🌐 Host: {SERVER_HOST}:{SERVER_PORT}")
    logger.info(f"🔧 Debug Mode: {DEBUG_MODE}")
    logger.info(f"📦 Max Payload: {SERVER_INFO['max_payload_mb']}MB")
    logger.info(f"⏱️ Max Duration: {SERVER_INFO['max_duration_minutes']} minutes")
    logger.info(f"⏰ Startup Time: {SERVER_INFO['startup_time']}")
    logger.info("=" * 70)


def main():
    """Main server function that starts the MCP server."""
    try:
        setup_server_logging()
        
        # Log available tools
        logger.info("🔧 Available Computational Tools:")
        tools = [
            "matrix_operations - Large matrix computations",
            "monte_carlo_simulation - Configurable Monte Carlo simulations",
            "prime_factorization - Large number prime factorization", 
            "data_aggregation - Process and aggregate large datasets",
            "hash_computation - Compute hashes with configurable iterations",
            "get_server_status - Server status and resource information"
        ]
        for tool in tools:
            logger.info(f"   - {tool}")
        
        logger.info("🌐 Starting server with streamable-http transport...")
        mcp.run(transport="streamable-http")
        
    except Exception as e:
        logger.error(f"💥 Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()