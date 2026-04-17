#!/usr/bin/env python3
"""
Bearer Token Refresh Utility for MCP Server

This utility refreshes the Cognito bearer token and updates it in AWS Secrets Manager.
The bearer token is used for authenticating with the MCP server deployed on AgentCore Runtime.

Features:
- Retrieves current Cognito configuration from Secrets Manager
- Authenticates with Cognito to get a fresh bearer token
- Updates the token in Secrets Manager
- Validates the new token works with the MCP server
- Supports both manual execution and scheduled automation
- Comprehensive logging and error handling

Usage:
    # Manual refresh
    python refresh_bearer_token.py

    # Check token expiry without refreshing
    python refresh_bearer_token.py --check-only

    # Refresh with validation
    python refresh_bearer_token.py --validate

    # Scheduled execution (cron-friendly)
    python refresh_bearer_token.py --quiet

Scheduling:
    # Add to crontab for automatic refresh every 30 minutes
    */30 * * * * /path/to/venv/bin/python /path/to/refresh_bearer_token.py --quiet
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import boto3
from boto3.session import Session

# Configuration constants
SECRETS_MANAGER_SECRET_NAME = 'mcp_server/cognito/credentials'
DEPLOY_CREDENTIALS_SECRET_NAME = 'mcp_server/deploy/credentials'
SSM_PARAMETER_NAME = '/mcp_server/runtime/agent_arn'
TOKEN_REFRESH_BUFFER_MINUTES = 5  # Refresh token 5 minutes before expiry


class TokenRefreshError(Exception):
    """Custom exception for token refresh errors."""
    pass


class CognitoTokenManager:
    """
    Manages Cognito authentication tokens for MCP server access.
    
    This class handles the complete lifecycle of Cognito tokens including
    retrieval of current configuration, authentication, and token updates.
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
            TokenRefreshError: If configuration cannot be retrieved
        """
        try:
            self.log("🔍 Retrieving current Cognito configuration...")
            
            response = self.secrets_client.get_secret_value(SecretId=SECRETS_MANAGER_SECRET_NAME)
            secret_value = response['SecretString']
            config = json.loads(secret_value)
            
            required_keys = ['pool_id', 'client_id', 'bearer_token', 'discovery_url']
            missing_keys = [key for key in required_keys if key not in config]
            
            if missing_keys:
                raise TokenRefreshError(f"Missing required configuration keys: {missing_keys}")
            
            self.log("✅ Successfully retrieved Cognito configuration")
            return config
            
        except self.secrets_client.exceptions.ResourceNotFoundException:
            raise TokenRefreshError(f"Secrets Manager secret '{SECRETS_MANAGER_SECRET_NAME}' not found")
        except json.JSONDecodeError as e:
            raise TokenRefreshError(f"Invalid JSON in secrets: {e}")
        except Exception as e:
            raise TokenRefreshError(f"Failed to retrieve configuration: {e}")
    
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
                
                # Check if token expires within the buffer time
                buffer_time = datetime.now() + timedelta(minutes=TOKEN_REFRESH_BUFFER_MINUTES)
                needs_refresh = expiry_time <= buffer_time
                
                if needs_refresh:
                    self.log(f"🕐 Token expires at {expiry_time}, refresh needed")
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
            Fresh bearer token
            
        Raises:
            TokenRefreshError: If authentication fails
        """
        try:
            self.log("🔐 Authenticating with Cognito to get fresh token...")
            
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
                raise TokenRefreshError("Authentication failed - no result returned")
            
            new_token = auth_response['AuthenticationResult']['AccessToken']
            
            self.log("✅ Successfully obtained fresh bearer token")
            return new_token
            
        except self.cognito_client.exceptions.NotAuthorizedException:
            raise TokenRefreshError("Authentication failed - invalid credentials")
        except self.cognito_client.exceptions.UserNotFoundException:
            raise TokenRefreshError("Authentication failed - user not found")
        except Exception as e:
            raise TokenRefreshError(f"Authentication failed: {e}")
    
    def update_token_in_secrets(self, config: Dict[str, str], new_token: str) -> None:
        """
        Update the bearer token in AWS Secrets Manager.
        
        Args:
            config: Current configuration dictionary
            new_token: New bearer token to store
            
        Raises:
            TokenRefreshError: If update fails
        """
        try:
            self.log("💾 Updating bearer token in Secrets Manager...")
            
            # Update the configuration with new token
            updated_config = config.copy()
            updated_config['bearer_token'] = new_token
            updated_config['last_refreshed'] = datetime.now().isoformat()
            
            # Store updated configuration
            self.secrets_client.update_secret(
                SecretId=SECRETS_MANAGER_SECRET_NAME,
                SecretString=json.dumps(updated_config)
            )
            
            self.log("✅ Successfully updated bearer token in Secrets Manager")
            
        except Exception as e:
            raise TokenRefreshError(f"Failed to update token in Secrets Manager: {e}")
    
    def validate_new_token(self, new_token: str) -> bool:
        """
        Validate that the new token works by making a test request to the MCP server.
        
        Args:
            new_token: New bearer token to validate
            
        Returns:
            True if token is valid, False otherwise
        """
        try:
            self.log("🧪 Validating new token with MCP server...")
            
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
                    timeout = timedelta(seconds=30)
                    async with streamablehttp_client(mcp_url, headers, timeout=timeout, terminate_on_close=False) as (
                        read_stream, write_stream, _
                    ):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            # Try to list tools as a simple test
                            await session.list_tools()
                            return True
                except Exception as e:
                    self.log(f"⚠️ Token validation failed: {e}", "WARNING")
                    return False
            
            # Run the async test
            result = asyncio.run(test_connection())
            
            if result:
                self.log("✅ New token validated successfully")
            else:
                self.log("❌ New token validation failed", "ERROR")
            
            return result
            
        except Exception as e:
            self.log(f"⚠️ Token validation error: {e}", "WARNING")
            return False
    
    def refresh_token(self, validate: bool = False) -> Dict[str, any]:
        """
        Complete token refresh process.
        
        Args:
            validate: Whether to validate the new token with MCP server
            
        Returns:
            Dictionary with refresh results and metadata
            
        Raises:
            TokenRefreshError: If refresh process fails
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
                    raise TokenRefreshError("New token validation failed")
            
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
                'validated': validate
            }
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            self.log(f"❌ Token refresh failed: {e}", "ERROR")
            
            return {
                'success': False,
                'error': str(e),
                'duration_seconds': duration
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
    """Main function for token refresh utility."""
    parser = argparse.ArgumentParser(
        description="Refresh Cognito bearer token for MCP server authentication",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python refresh_bearer_token.py                    # Refresh token
  python refresh_bearer_token.py --check-only       # Check expiry only
  python refresh_bearer_token.py --validate         # Refresh and validate
  python refresh_bearer_token.py --quiet            # Silent mode for cron
  
Scheduling:
  # Add to crontab for automatic refresh every 30 minutes
  */30 * * * * /path/to/venv/bin/python /path/to/refresh_bearer_token.py --quiet
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
        help='Validate new token by testing MCP server connection'
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
        token_manager = CognitoTokenManager(region, quiet=args.quiet)
        
        if not args.quiet:
            print("🔄 MCP Server Bearer Token Refresh Utility")
            print("=" * 50)
            print(f"🌍 AWS Region: {region}")
        
        if args.check_only:
            # Only check token expiry
            config = token_manager.get_current_config()
            current_token = config.get('bearer_token', '')
            needs_refresh, expiry_time = token_manager.check_token_expiry(current_token)
            
            if not args.quiet:
                if expiry_time:
                    print(f"🕐 Token expires: {expiry_time}")
                    print(f"🔄 Refresh needed: {'Yes' if needs_refresh else 'No'}")
                else:
                    print("⚠️ Could not determine token expiry")
            
            sys.exit(0 if not needs_refresh else 1)
        
        # Perform token refresh
        if args.force:
            # Force refresh by temporarily modifying the check
            original_buffer = TOKEN_REFRESH_BUFFER_MINUTES
            import refresh_bearer_token
            refresh_bearer_token.TOKEN_REFRESH_BUFFER_MINUTES = 999999  # Force refresh
        
        result = token_manager.refresh_token(validate=args.validate)
        
        if args.force:
            # Restore original buffer
            refresh_bearer_token.TOKEN_REFRESH_BUFFER_MINUTES = original_buffer
        
        if not args.quiet:
            print(f"\n📊 Refresh Results:")
            print(f"   Success: {'✅' if result['success'] else '❌'}")
            print(f"   Action: {result.get('action', 'unknown')}")
            print(f"   Duration: {result['duration_seconds']:.2f}s")
            
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