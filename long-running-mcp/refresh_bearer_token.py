#!/usr/bin/env python3
"""
Bearer Token Refresh Utility for Long-Running MCP Server

This utility refreshes the Cognito bearer token for the long-running MCP server
and updates it in AWS Secrets Manager. Extended token validity for long operations.

Features:
- Retrieves current Cognito configuration from Secrets Manager
- Authenticates with Cognito to get a fresh bearer token
- Updates the token in Secrets Manager
- Validates the new token works with the long-running MCP server
- Extended token validity for long-running operations
- Comprehensive logging and error handling

Usage:
    # Manual refresh
    python token_refresh.py

    # Check token expiry without refreshing
    python token_refresh.py --check-only

    # Refresh with validation
    python token_refresh.py --validate

    # Scheduled execution (cron-friendly)
    python token_refresh.py --quiet

Scheduling:
    # Add to crontab for automatic refresh every 6 hours (for 12-hour tokens)
    0 */6 * * * /path/to/venv/bin/python /path/to/token_refresh.py --quiet
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import boto3
from boto3.session import Session

# Configuration constants
SECRETS_MANAGER_SECRET_NAME = 'long_running_mcp_server/cognito/credentials'
DEPLOY_CREDENTIALS_SECRET_NAME = 'long_running_mcp_server/deploy/credentials'
SSM_PARAMETER_NAME = '/long_running_mcp_server/runtime/agent_arn'
TOKEN_REFRESH_BUFFER_HOURS = 2  # Refresh token 2 hours before expiry (for 12-hour tokens)


class LongRunningTokenRefreshError(Exception):
    """Custom exception for token refresh errors."""
    pass


class LongRunningCognitoTokenManager:
    """
    Manages Cognito authentication tokens for long-running MCP server access.
    
    This class handles the complete lifecycle of Cognito tokens including
    retrieval of current configuration, authentication, and token updates
    with extended validity for long-running operations.
    """
    
    def __init__(self, region: str, quiet: bool = False):
        self.region = region
        self.quiet = quiet
        self.cognito_client = boto3.client('cognito-idp', region_name=region)
        self.secrets_client = boto3.client('secretsmanager', region_name=region)
        
    def log(self, message: str, level: str = "INFO"):
        """Log messages unless in quiet mode."""
        if not self.quiet:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] {level}: {message}")
    
    def get_current_config(self) -> Dict[str, str]:
        """
        Retrieve current Cognito configuration from Secrets Manager.
        
        Returns:
            Dict containing Cognito configuration including credentials
            
        Raises:
            LongRunningTokenRefreshError: If configuration cannot be retrieved
        """
        try:
            self.log("🔍 Retrieving current Cognito configuration for long-running MCP server...")
            
            response = self.secrets_client.get_secret_value(SecretId=SECRETS_MANAGER_SECRET_NAME)
            secret_value = response['SecretString']
            config = json.loads(secret_value)
            
            required_keys = ['pool_id', 'client_id', 'bearer_token', 'discovery_url']
            missing_keys = [key for key in required_keys if key not in config]
            
            if missing_keys:
                raise LongRunningTokenRefreshError(f"Missing required configuration keys: {missing_keys}")
            
            self.log("✅ Successfully retrieved Cognito configuration")
            return config
            
        except self.secrets_client.exceptions.ResourceNotFoundException:
            raise LongRunningTokenRefreshError(f"Secrets Manager secret '{SECRETS_MANAGER_SECRET_NAME}' not found")
        except json.JSONDecodeError as e:
            raise LongRunningTokenRefreshError(f"Invalid JSON in secrets: {e}")
        except Exception as e:
            raise LongRunningTokenRefreshError(f"Failed to retrieve configuration: {e}")
    
    def check_token_expiry(self, bearer_token: str) -> Tuple[bool, Optional[datetime]]:
        """
        Check if the current bearer token is expired or will expire soon.
        
        Args:
            bearer_token: Current bearer token to check
            
        Returns:
            Tuple of (needs_refresh: bool, expiry_time: Optional[datetime])
        """
        try:
            # Decode JWT token to check expiry (basic check without verification)
            import base64
            
            # JWT tokens have 3 parts separated by dots
            parts = bearer_token.split('.')
            if len(parts) != 3:
                self.log("⚠️ Invalid JWT token format", "WARNING")
                return True, None
            
            # Decode the payload (second part)
            # Add padding if needed
            payload = parts[1]
            padding = 4 - (len(payload) % 4)
            if padding != 4:
                payload += '=' * padding
            
            decoded_payload = base64.urlsafe_b64decode(payload)
            token_data = json.loads(decoded_payload)
            
            # Check expiry time
            if 'exp' in token_data:
                expiry_timestamp = token_data['exp']
                expiry_time = datetime.fromtimestamp(expiry_timestamp)
                
                # Check if token expires within the buffer time (2 hours for 12-hour tokens)
                buffer_time = datetime.now() + timedelta(hours=TOKEN_REFRESH_BUFFER_HOURS)
                needs_refresh = expiry_time <= buffer_time
                
                if needs_refresh:
                    self.log(f"🕐 Token expires at {expiry_time}, refresh needed (buffer: {TOKEN_REFRESH_BUFFER_HOURS}h)")
                else:
                    self.log(f"✅ Token valid until {expiry_time}")
                
                return needs_refresh, expiry_time
            else:
                self.log("⚠️ No expiry information in token", "WARNING")
                return True, None
                
        except Exception as e:
            self.log(f"⚠️ Error checking token expiry: {e}", "WARNING")
            return True, None
    
    def authenticate_and_get_token(self, config: Dict[str, str]) -> str:
        """
        Authenticate with Cognito and get a fresh bearer token.
        
        Args:
            config: Cognito configuration dictionary
            
        Returns:
            Fresh bearer token with extended validity
            
        Raises:
            LongRunningTokenRefreshError: If authentication fails
        """
        try:
            self.log("🔐 Authenticating with Cognito to get fresh token for long-running operations...")
            
            # Read credentials from the separate deploy credentials secret
            creds_response = self.secrets_client.get_secret_value(SecretId=DEPLOY_CREDENTIALS_SECRET_NAME)
            creds = json.loads(creds_response['SecretString'])
            username = creds['username']
            password = creds['password']
            
            auth_response = self.cognito_client.initiate_auth(
                ClientId=config['client_id'],
                AuthFlow='USER_PASSWORD_AUTH',
                AuthParameters={
                    'USERNAME': username,
                    'PASSWORD': password
                }
            )
            
            if 'AuthenticationResult' not in auth_response:
                raise LongRunningTokenRefreshError("Authentication failed - no result returned")
            
            new_token = auth_response['AuthenticationResult']['AccessToken']
            
            # Log token validity information
            try:
                import base64
                parts = new_token.split('.')
                if len(parts) == 3:
                    payload = parts[1]
                    padding = 4 - (len(payload) % 4)
                    if padding != 4:
                        payload += '=' * padding
                    decoded_payload = base64.urlsafe_b64decode(payload)
                    token_data = json.loads(decoded_payload)
                    if 'exp' in token_data:
                        expiry_time = datetime.fromtimestamp(token_data['exp'])
                        validity_hours = (expiry_time - datetime.now()).total_seconds() / 3600
                        self.log(f"✅ New token valid for {validity_hours:.1f} hours (until {expiry_time})")
            except:
                pass  # Skip token analysis if it fails
            
            self.log("✅ Successfully obtained fresh bearer token")
            return new_token
            
        except self.cognito_client.exceptions.NotAuthorizedException:
            raise LongRunningTokenRefreshError("Authentication failed - invalid credentials")
        except self.cognito_client.exceptions.UserNotFoundException:
            raise LongRunningTokenRefreshError("Authentication failed - user not found")
        except Exception as e:
            raise LongRunningTokenRefreshError(f"Authentication failed: {e}")
    
    def update_token_in_secrets(self, config: Dict[str, str], new_token: str) -> None:
        """
        Update the bearer token in AWS Secrets Manager.
        
        Args:
            config: Current configuration dictionary
            new_token: New bearer token to store
            
        Raises:
            LongRunningTokenRefreshError: If update fails
        """
        try:
            self.log("💾 Updating bearer token in Secrets Manager...")
            
            # Update the configuration with new token
            updated_config = config.copy()
            updated_config['bearer_token'] = new_token
            updated_config['last_refreshed'] = datetime.now().isoformat()
            updated_config['refresh_reason'] = 'scheduled_refresh_for_long_running_operations'
            
            # Store updated configuration
            self.secrets_client.update_secret(
                SecretId=SECRETS_MANAGER_SECRET_NAME,
                SecretString=json.dumps(updated_config)
            )
            
            self.log("✅ Successfully updated bearer token in Secrets Manager")
            
        except Exception as e:
            raise LongRunningTokenRefreshError(f"Failed to update token in Secrets Manager: {e}")
    
    def validate_new_token(self, new_token: str) -> bool:
        """
        Validate that the new token works by making a test request to the long-running MCP server.
        
        Args:
            new_token: New bearer token to validate
            
        Returns:
            True if token is valid, False otherwise
        """
        try:
            self.log("🧪 Validating new token with long-running MCP server...")
            
            # Get the agent ARN for constructing the MCP URL
            ssm_client = boto3.client('ssm', region_name=self.region)
            agent_arn_response = ssm_client.get_parameter(Name=SSM_PARAMETER_NAME)
            agent_arn = agent_arn_response['Parameter']['Value']
            
            # Import here to avoid dependency issues if not needed
            import asyncio
            from urllib.parse import quote
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
            from datetime import timedelta
            
            # Construct MCP URL
            encoded_arn = quote(agent_arn, safe='')
            mcp_url = f"https://bedrock-agentcore.{self.region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"
            
            headers = {
                "authorization": f"Bearer {new_token}",
                "Content-Type": "application/json"
            }
            
            async def test_connection():
                try:
                    timeout = timedelta(seconds=60)  # Extended timeout for long-running server
                    
                    async with streamablehttp_client(mcp_url, headers, timeout=timeout, terminate_on_close=False) as (
                        read_stream, write_stream, _
                    ):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            # Try to list tools as a simple test
                            tools_result = await session.list_tools()
                            
                            # Try to get server status for additional validation
                            status_result = await session.call_tool(name="get_server_status", arguments={})
                            
                            return True
                except Exception as e:
                    self.log(f"⚠️ Token validation failed: {e}", "WARNING")
                    return False
            
            # Run the async test
            result = asyncio.run(test_connection())
            
            if result:
                self.log("✅ New token validated successfully with long-running MCP server")
            else:
                self.log("❌ New token validation failed", "ERROR")
            
            return result
            
        except Exception as e:
            self.log(f"⚠️ Token validation error: {e}", "WARNING")
            return False
    
    def refresh_token(self, validate: bool = False) -> Dict[str, any]:
        """
        Complete token refresh process for long-running operations.
        
        Args:
            validate: Whether to validate the new token with MCP server
            
        Returns:
            Dictionary with refresh results and metadata
            
        Raises:
            LongRunningTokenRefreshError: If refresh process fails
        """
        start_time = datetime.now()
        
        try:
            # Get current configuration
            config = self.get_current_config()
            
            # Check if refresh is needed
            current_token = config.get('bearer_token', '')
            needs_refresh, expiry_time = self.check_token_expiry(current_token)
            
            if not needs_refresh:
                self.log("ℹ️ Token refresh not needed at this time")
                return {
                    'success': True,
                    'action': 'no_refresh_needed',
                    'expiry_time': expiry_time.isoformat() if expiry_time else None,
                    'duration_seconds': (datetime.now() - start_time).total_seconds()
                }
            
            # Authenticate and get new token
            new_token = self.authenticate_and_get_token(config)
            
            # Validate new token if requested
            if validate:
                if not self.validate_new_token(new_token):
                    raise LongRunningTokenRefreshError("New token validation failed")
            
            # Update token in Secrets Manager
            self.update_token_in_secrets(config, new_token)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            self.log(f"🎉 Token refresh completed successfully in {duration:.2f} seconds")
            
            return {
                'success': True,
                'action': 'token_refreshed',
                'old_expiry': expiry_time.isoformat() if expiry_time else None,
                'refresh_time': end_time.isoformat(),
                'duration_seconds': duration,
                'validated': validate,
                'server_type': 'long_running_computational'
            }
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            self.log(f"❌ Token refresh failed: {e}", "ERROR")
            
            return {
                'success': False,
                'error': str(e),
                'duration_seconds': duration,
                'server_type': 'long_running_computational'
            }


def get_aws_region() -> str:
    """Get the current AWS region from boto3 session."""
    try:
        boto_session = Session()
        region = boto_session.region_name
        if not region:
            raise RuntimeError("AWS region not configured")
        return region
    except Exception as e:
        raise RuntimeError(f"Failed to get AWS region: {e}")


def main():
    """Main function for long-running MCP server token refresh utility."""
    parser = argparse.ArgumentParser(
        description="Refresh Cognito bearer token for long-running MCP server authentication",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python token_refresh.py                    # Refresh token
  python token_refresh.py --check-only       # Check expiry only
  python token_refresh.py --validate         # Refresh and validate
  python token_refresh.py --quiet            # Silent mode for cron
  
Scheduling for Long-Running Operations:
  # Add to crontab for automatic refresh every 6 hours (for 12-hour tokens)
  0 */6 * * * /path/to/venv/bin/python /path/to/token_refresh.py --quiet
        """
    )
    
    parser.add_argument(
        '--check-only',
        action='store_true',
        help='Only check token expiry, do not refresh'
    )
    
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate new token by testing long-running MCP server connection'
    )
    
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Suppress output (useful for scheduled execution)'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force refresh even if token is not expired'
    )
    
    args = parser.parse_args()
    
    try:
        # Get AWS region
        region = get_aws_region()
        
        # Initialize token manager
        token_manager = LongRunningCognitoTokenManager(region, quiet=args.quiet)
        
        if not args.quiet:
            print("🔄 Long-Running MCP Server Bearer Token Refresh Utility")
            print("=" * 60)
            print(f"🌍 AWS Region: {region}")
            print("⚡ Optimized for long-running computational operations")
        
        if args.check_only:
            # Only check token expiry
            config = token_manager.get_current_config()
            current_token = config.get('bearer_token', '')
            needs_refresh, expiry_time = token_manager.check_token_expiry(current_token)
            
            if not args.quiet:
                if expiry_time:
                    print(f"🕐 Token expires: {expiry_time}")
                    print(f"🔄 Refresh needed: {'Yes' if needs_refresh else 'No'}")
                    validity_hours = (expiry_time - datetime.now()).total_seconds() / 3600
                    print(f"⏱️ Time remaining: {validity_hours:.1f} hours")
                else:
                    print("⚠️ Could not determine token expiry")
            
            sys.exit(0 if not needs_refresh else 1)
        
        # Perform token refresh
        if args.force:
            # Force refresh by temporarily modifying the check
            original_buffer = TOKEN_REFRESH_BUFFER_HOURS
            import token_refresh
            token_refresh.TOKEN_REFRESH_BUFFER_HOURS = 999999  # Force refresh
        
        result = token_manager.refresh_token(validate=args.validate)
        
        if args.force:
            # Restore original buffer
            token_refresh.TOKEN_REFRESH_BUFFER_HOURS = original_buffer
        
        if not args.quiet:
            print(f"\n📊 Refresh Results:")
            print(f"   Success: {'✅' if result['success'] else '❌'}")
            print(f"   Action: {result.get('action', 'unknown')}")
            print(f"   Duration: {result['duration_seconds']:.2f}s")
            print(f"   Server Type: {result.get('server_type', 'unknown')}")
            
            if result['success'] and result.get('action') == 'token_refreshed':
                print(f"   Validated: {'✅' if result.get('validated') else '⏭️ Skipped'}")
        
        # Exit with appropriate code
        sys.exit(0 if result['success'] else 1)
        
    except KeyboardInterrupt:
        if not args.quiet:
            print(f"\n⏹️ Token refresh interrupted by user")
        sys.exit(130)  # Standard exit code for Ctrl+C
        
    except Exception as e:
        if not args.quiet:
            print(f"\n💥 Token refresh failed: {e}")
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()