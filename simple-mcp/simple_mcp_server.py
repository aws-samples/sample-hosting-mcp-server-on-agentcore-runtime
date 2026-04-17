#!/usr/bin/env python3
"""
MCP Server for Amazon Bedrock AgentCore Runtime

This server implements the Model Context Protocol (MCP) and provides
mathematical and utility tools for demonstration purposes.

Features:
- Mathematical operations (addition, multiplication, division, power)
- String utilities (greeting, text processing)
- Data validation and error handling
- Comprehensive logging and monitoring
- Health check endpoint

The server is designed to run on Amazon Bedrock AgentCore Runtime
with JWT authentication and stateless HTTP transport.
"""

import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

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
    "name": "MCP Math & Utility Server",
    "version": "1.0.0",
    "description": "Provides mathematical operations and utility functions",
    "author": "AWS Bedrock AgentCore Demo",
    "startup_time": datetime.now().isoformat()
}


@mcp.tool()
def add_numbers(a: Union[int, float], b: Union[int, float]) -> Union[int, float]:
    """
    Add two numbers together.
    
    This tool performs basic addition of two numeric values.
    Supports both integers and floating-point numbers.
    
    Args:
        a: First number to add
        b: Second number to add
        
    Returns:
        The sum of a and b
        
    Examples:
        add_numbers(5, 3) -> 8
        add_numbers(2.5, 1.5) -> 4.0
    """
    try:
        result = a + b
        logger.info(f"Addition: {a} + {b} = {result}")
        return result
    except Exception as e:
        logger.error(f"Error in add_numbers: {e}")
        raise ValueError(f"Failed to add numbers: {e}")


@mcp.tool()
def multiply_numbers(a: Union[int, float], b: Union[int, float]) -> Union[int, float]:
    """
    Multiply two numbers together.
    
    This tool performs basic multiplication of two numeric values.
    Supports both integers and floating-point numbers.
    
    Args:
        a: First number to multiply
        b: Second number to multiply
        
    Returns:
        The product of a and b
        
    Examples:
        multiply_numbers(4, 7) -> 28
        multiply_numbers(2.5, 4) -> 10.0
    """
    try:
        result = a * b
        logger.info(f"Multiplication: {a} × {b} = {result}")
        return result
    except Exception as e:
        logger.error(f"Error in multiply_numbers: {e}")
        raise ValueError(f"Failed to multiply numbers: {e}")


@mcp.tool()
def divide_numbers(a: Union[int, float], b: Union[int, float]) -> float:
    """
    Divide two numbers.
    
    This tool performs division of two numeric values with proper
    error handling for division by zero.
    
    Args:
        a: Dividend (number to be divided)
        b: Divisor (number to divide by)
        
    Returns:
        The quotient of a divided by b
        
    Raises:
        ValueError: If attempting to divide by zero
        
    Examples:
        divide_numbers(10, 2) -> 5.0
        divide_numbers(7, 3) -> 2.333...
    """
    try:
        if b == 0:
            raise ValueError("Cannot divide by zero")
        
        result = a / b
        logger.info(f"Division: {a} ÷ {b} = {result}")
        return result
    except Exception as e:
        logger.error(f"Error in divide_numbers: {e}")
        raise ValueError(f"Failed to divide numbers: {e}")


@mcp.tool()
def power_numbers(base: Union[int, float], exponent: Union[int, float]) -> Union[int, float]:
    """
    Raise a number to a power.
    
    This tool calculates base raised to the power of exponent.
    Includes validation for edge cases and potential overflow.
    
    Args:
        base: The base number
        exponent: The exponent (power)
        
    Returns:
        base raised to the power of exponent
        
    Examples:
        power_numbers(2, 3) -> 8
        power_numbers(5, 2) -> 25
        power_numbers(4, 0.5) -> 2.0
    """
    try:
        # Check for potential overflow with large numbers
        if abs(base) > 1000 and abs(exponent) > 10:
            raise ValueError("Numbers too large, potential overflow")
        
        result = base ** exponent
        logger.info(f"Power: {base}^{exponent} = {result}")
        return result
    except Exception as e:
        logger.error(f"Error in power_numbers: {e}")
        raise ValueError(f"Failed to calculate power: {e}")


@mcp.tool()
def greet_user(name: str, language: str = "en") -> str:
    """
    Greet a user by name in different languages.
    
    This tool provides personalized greetings with support for
    multiple languages and input validation.
    
    Args:
        name: The name of the person to greet
        language: Language code for the greeting (default: "en")
        
    Returns:
        A personalized greeting message
        
    Examples:
        greet_user("Alice") -> "Hello, Alice! Nice to meet you."
        greet_user("Bob", "es") -> "¡Hola, Bob! Mucho gusto."
    """
    try:
        # Input validation
        if not name or not isinstance(name, str):
            raise ValueError("Name must be a non-empty string")
        
        name = name.strip()
        if not name:
            raise ValueError("Name cannot be empty or just whitespace")
        
        # Greeting templates by language
        greetings = {
            "en": f"Hello, {name}! Nice to meet you.",
            "es": f"¡Hola, {name}! Mucho gusto.",
            "fr": f"Bonjour, {name}! Ravi de vous rencontrer.",
            "de": f"Hallo, {name}! Schön, Sie kennenzulernen.",
            "it": f"Ciao, {name}! Piacere di conoscerti.",
            "pt": f"Olá, {name}! Prazer em conhecê-lo.",
            "ja": f"こんにちは、{name}さん！はじめまして。",
            "zh": f"你好，{name}！很高兴认识你。"
        }
        
        greeting = greetings.get(language.lower(), greetings["en"])
        logger.info(f"Greeting generated for {name} in {language}")
        return greeting
        
    except Exception as e:
        logger.error(f"Error in greet_user: {e}")
        raise ValueError(f"Failed to generate greeting: {e}")


@mcp.tool()
def calculate_statistics(numbers: List[Union[int, float]]) -> Dict[str, float]:
    """
    Calculate basic statistics for a list of numbers.
    
    This tool computes mean, median, min, max, and standard deviation
    for a given list of numeric values.
    
    Args:
        numbers: List of numbers to analyze
        
    Returns:
        Dictionary containing statistical measures
        
    Examples:
        calculate_statistics([1, 2, 3, 4, 5]) -> {
            "mean": 3.0,
            "median": 3.0,
            "min": 1,
            "max": 5,
            "std_dev": 1.58,
            "count": 5
        }
    """
    try:
        if not numbers or not isinstance(numbers, list):
            raise ValueError("Input must be a non-empty list of numbers")
        
        if not all(isinstance(n, (int, float)) for n in numbers):
            raise ValueError("All elements must be numbers")
        
        count = len(numbers)
        mean = sum(numbers) / count
        sorted_nums = sorted(numbers)
        
        # Calculate median
        if count % 2 == 0:
            median = (sorted_nums[count//2 - 1] + sorted_nums[count//2]) / 2
        else:
            median = sorted_nums[count//2]
        
        # Calculate standard deviation
        variance = sum((x - mean) ** 2 for x in numbers) / count
        std_dev = variance ** 0.5
        
        result = {
            "mean": round(mean, 2),
            "median": median,
            "min": min(numbers),
            "max": max(numbers),
            "std_dev": round(std_dev, 2),
            "count": count
        }
        
        logger.info(f"Statistics calculated for {count} numbers")
        return result
        
    except Exception as e:
        logger.error(f"Error in calculate_statistics: {e}")
        raise ValueError(f"Failed to calculate statistics: {e}")


@mcp.tool()
def format_text(text: str, operation: str = "upper") -> str:
    """
    Format text using various string operations.
    
    This tool provides common text formatting operations with
    input validation and error handling.
    
    Args:
        text: The text to format
        operation: Type of formatting ("upper", "lower", "title", "reverse")
        
    Returns:
        Formatted text string
        
    Examples:
        format_text("hello world", "upper") -> "HELLO WORLD"
        format_text("HELLO WORLD", "title") -> "Hello World"
    """
    try:
        if not isinstance(text, str):
            raise ValueError("Text must be a string")
        
        operations = {
            "upper": text.upper,
            "lower": text.lower,
            "title": text.title,
            "reverse": lambda: text[::-1],
            "capitalize": text.capitalize,
            "strip": text.strip
        }
        
        if operation not in operations:
            available_ops = ", ".join(operations.keys())
            raise ValueError(f"Invalid operation. Available: {available_ops}")
        
        result = operations[operation]()
        logger.info(f"Text formatted using '{operation}' operation")
        return result
        
    except Exception as e:
        logger.error(f"Error in format_text: {e}")
        raise ValueError(f"Failed to format text: {e}")


@mcp.tool()
def get_server_info() -> Dict[str, str]:
    """
    Get information about the MCP server.
    
    This tool provides metadata about the server including
    version, capabilities, and runtime information.
    
    Returns:
        Dictionary containing server information
    """
    try:
        current_time = datetime.now().isoformat()
        info = {
            **SERVER_INFO,
            "current_time": current_time,
            "status": "running",
            "tools_available": "8"
        }
        
        logger.info("Server info requested")
        return info
        
    except Exception as e:
        logger.error(f"Error in get_server_info: {e}")
        raise ValueError(f"Failed to get server info: {e}")


def setup_server_logging():
    """Configure server logging and startup information."""
    logger.info("=" * 60)
    logger.info("🚀 Starting MCP Server for AgentCore Runtime")
    logger.info(f"📊 Server: {SERVER_INFO['name']} v{SERVER_INFO['version']}")
    logger.info(f"🌐 Host: {SERVER_HOST}")
    logger.info(f"🔧 Debug Mode: {DEBUG_MODE}")
    logger.info(f"⏰ Startup Time: {SERVER_INFO['startup_time']}")
    logger.info("=" * 60)


def main():
    """
    Main server function that starts the MCP server.
    """
    try:
        setup_server_logging()
        
        # Log available tools
        logger.info("🔧 Available Tools:")
        tools = [
            "add_numbers", "multiply_numbers", "divide_numbers", "power_numbers",
            "greet_user", "calculate_statistics", "format_text", "get_server_info"
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
