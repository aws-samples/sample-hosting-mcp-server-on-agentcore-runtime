#!/usr/bin/env python3
"""
MCP Server AgentCore Runtime Deployment Script

This script automates the deployment of an MCP (Model Context Protocol) server 
to Amazon Bedrock AgentCore Runtime with Cognito authentication.

Features:
- Creates Cognito User Pool for authentication
- Deploys MCP server to AgentCore Runtime
- Stores credentials in AWS Secrets Manager and Parameter Store
- Monitors deployment status

Requirements:
- long_running_mcp_server.py: The MCP server implementation
- requirements.txt: Python dependencies
- AWS credentials configured
"""

import os
import sys
import time
import json
import boto3
from boto3.session import Session
from bedrock_agentcore_starter_toolkit import Runtime

# Configuration constants
COGNITO_POOL_NAME = 'MCPServerPool'
COGNITO_CLIENT_NAME = 'MCPServerPoolClient'
AGENT_NAME = 'mcp_server_agentcore'
REQUIRED_FILES = ['simple_mcp_server.py', 'requirements.txt']

# AWS resource names
SECRETS_MANAGER_SECRET_NAME = 'mcp_server/cognito/credentials'
DEPLOY_CREDENTIALS_SECRET_NAME = 'mcp_server/deploy/credentials'
SSM_PARAMETER_NAME = '/mcp_server/runtime/agent_arn'


def get_credentials_from_env() -> tuple:
    """
    Read Cognito credentials from environment variables.

    Returns:
        Tuple of (username, password)
    """
    username = os.environ.get('MCP_USERNAME')
    password = os.environ.get('MCP_PASSWORD')
    return username, password


def setup_cognito_user_pool(region: str, username: str, password: str) -> dict:
    """
    Create and configure a Cognito User Pool for MCP server authentication.
    
    This function:
    1. Creates a Cognito User Pool with password policy
    2. Creates an app client for authentication
    3. Creates a test user with permanent password
    4. Authenticates the user to get an access token
    
    Args:
        region (str): AWS region for Cognito resources
        username (str): Cognito username
        password (str): Cognito password
        
    Returns:
        dict: Configuration containing pool_id, client_id, bearer_token, and discovery_url
        
    Raises:
        Exception: If Cognito setup fails
    """
    print("🔧 Setting up Amazon Cognito user pool...")
    
    cognito_client = boto3.client('cognito-idp', region_name=region)
    
    try:
        # Create User Pool with password policy
        user_pool_response = cognito_client.create_user_pool(
            PoolName=COGNITO_POOL_NAME,
            Policies={
                'PasswordPolicy': {
                    'MinimumLength': 8,
                    'RequireUppercase': True,
                    'RequireLowercase': True,
                    'RequireNumbers': True,
                    'RequireSymbols': True
                }
            }
        )
        pool_id = user_pool_response['UserPool']['Id']
        print(f"✓ Created User Pool: {pool_id}")
        
        # Create App Client for authentication
        app_client_response = cognito_client.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName=COGNITO_CLIENT_NAME,
            GenerateSecret=False,  # No client secret for simplicity
            ExplicitAuthFlows=[
                'ALLOW_USER_PASSWORD_AUTH',
                'ALLOW_REFRESH_TOKEN_AUTH'
            ]
        )
        client_id = app_client_response['UserPoolClient']['ClientId']
        print(f"✓ Created App Client: {client_id}")
        
        # Create test user
        cognito_client.admin_create_user(
            UserPoolId=pool_id,
            Username=username,
            TemporaryPassword='Temp123!',
            MessageAction='SUPPRESS'  # Don't send welcome email
        )
        print(f"✓ Created test user: {username}")
        
        # Set permanent password for the test user
        cognito_client.admin_set_user_password(
            UserPoolId=pool_id,
            Username=username,
            Password=password,
            Permanent=True
        )
        print("✓ Set permanent password for test user")
        
        # Authenticate user to get access token
        auth_response = cognito_client.initiate_auth(
            ClientId=client_id,
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': password
            }
        )
        bearer_token = auth_response['AuthenticationResult']['AccessToken']
        print("✓ Generated bearer token")
        
        # Construct discovery URL for JWT validation
        discovery_url = f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
        
        config = {
            'pool_id': pool_id,
            'client_id': client_id,
            'bearer_token': bearer_token,
            'discovery_url': discovery_url
        }
        
        print("✅ Cognito setup completed successfully")
        return config
        
    except Exception as e:
        print(f"❌ Error setting up Cognito: {e}")
        raise


def validate_required_files() -> None:
    """
    Validate that all required files exist in the current directory.
    
    Raises:
        FileNotFoundError: If any required file is missing
    """
    print("📋 Validating required files...")
    
    for file in REQUIRED_FILES:
        if not os.path.exists(file):
            raise FileNotFoundError(f"Required file {file} not found in current directory")
    
    print("✓ All required files found")


def configure_agentcore_runtime(region: str, cognito_config: dict) -> Runtime:
    """
    Configure the AgentCore Runtime with MCP server settings.
    
    Args:
        region (str): AWS region for deployment
        cognito_config (dict): Cognito configuration from setup_cognito_user_pool
        
    Returns:
        Runtime: Configured AgentCore Runtime instance
    """
    print("⚙️ Configuring AgentCore Runtime...")
    
    agentcore_runtime = Runtime()
    
    # Configure JWT authorization with Cognito
    auth_config = {
        "customJWTAuthorizer": {
            "allowedClients": [cognito_config['client_id']],
            "discoveryUrl": cognito_config['discovery_url'],
        }
    }
    
    # Configure the runtime
    response = agentcore_runtime.configure(
        entrypoint="simple_mcp_server.py",
        auto_create_execution_role=True,
        auto_create_ecr=True,
        requirements_file="requirements.txt",
        region=region,
        authorizer_configuration=auth_config,
        protocol="MCP",
        agent_name=AGENT_NAME
    )
    
    print("✓ AgentCore Runtime configured")
    return agentcore_runtime


def deploy_and_monitor_runtime(agentcore_runtime: Runtime) -> object:
    """
    Deploy the MCP server to AgentCore Runtime and monitor until ready.
    
    Args:
        agentcore_runtime (Runtime): Configured runtime instance
        
    Returns:
        object: Launch result containing agent ARN and ID
    """
    print("🚀 Launching MCP server to AgentCore Runtime...")
    print("⏳ This may take several minutes...")
    
    # Launch the runtime
    launch_result = agentcore_runtime.launch()
    print("✓ Launch initiated")
    print(f"Agent ARN: {launch_result.agent_arn}")
    print(f"Agent ID: {launch_result.agent_id}")
    
    # Monitor deployment status
    print("📊 Monitoring deployment status...")
    status_response = agentcore_runtime.status()
    status = status_response.endpoint['status']
    print(f"Initial status: {status}")
    
    # Wait for final status
    end_statuses = ['READY', 'CREATE_FAILED', 'DELETE_FAILED', 'UPDATE_FAILED']
    while status not in end_statuses:
        print(f"Status: {status} - waiting...")
        time.sleep(10)
        status_response = agentcore_runtime.status()
        status = status_response.endpoint['status']
    
    # Report final status
    if status == 'READY':
        print("✅ AgentCore Runtime is READY!")
    else:
        print(f"⚠️ AgentCore Runtime status: {status}")
    
    return launch_result


def store_configuration(region: str, cognito_config: dict, launch_result: object, username: str, password: str) -> None:
    """
    Store configuration in AWS Secrets Manager and Parameter Store.
    
    Args:
        region (str): AWS region
        cognito_config (dict): Cognito configuration (no credentials)
        launch_result (object): Runtime launch result
        username (str): Cognito username to store in separate secret
        password (str): Cognito password to store in separate secret
    """
    print("💾 Storing configuration in AWS...")
    
    ssm_client = boto3.client('ssm', region_name=region)
    secrets_client = boto3.client('secretsmanager', region_name=region)
    
    # Store Cognito config in Secrets Manager (no credentials)
    try:
        secrets_client.create_secret(
            Name=SECRETS_MANAGER_SECRET_NAME,
            Description='Cognito credentials for MCP server',
            SecretString=json.dumps(cognito_config)
        )
        print("✓ Cognito credentials stored in Secrets Manager")
    except secrets_client.exceptions.ResourceExistsException:
        secrets_client.update_secret(
            SecretId=SECRETS_MANAGER_SECRET_NAME,
            SecretString=json.dumps(cognito_config)
        )
        print("✓ Cognito credentials updated in Secrets Manager")
    
    # Store deploy credentials in a separate secret
    deploy_creds = {'username': username, 'password': password}
    try:
        secrets_client.create_secret(
            Name=DEPLOY_CREDENTIALS_SECRET_NAME,
            Description='Deploy credentials for MCP server Cognito user',
            SecretString=json.dumps(deploy_creds)
        )
        print("✓ Deploy credentials stored in Secrets Manager")
    except secrets_client.exceptions.ResourceExistsException:
        secrets_client.update_secret(
            SecretId=DEPLOY_CREDENTIALS_SECRET_NAME,
            SecretString=json.dumps(deploy_creds)
        )
        print("✓ Deploy credentials updated in Secrets Manager")
    
    # Store Agent ARN in Parameter Store
    ssm_client.put_parameter(
        Name=SSM_PARAMETER_NAME,
        Value=launch_result.agent_arn,
        Type='String',
        Description='Agent ARN for MCP server',
        Overwrite=True
    )
    print("✓ Agent ARN stored in Parameter Store")


def main():
    """
    Main deployment function that orchestrates the entire process.
    """
    print("🎯 Starting MCP Server AgentCore Runtime Deployment")
    print("=" * 60)
    
    try:
        # Initialize AWS session and get region
        boto_session = Session()
        region = boto_session.region_name
        print(f"🌍 Using AWS region: {region}")
        
        # Read credentials from environment variables
        username, password = get_credentials_from_env()
        
        # Validate required files exist
        validate_required_files()
        
        # Setup Cognito authentication
        cognito_config = setup_cognito_user_pool(region, username, password)
        
        # Configure AgentCore Runtime
        agentcore_runtime = configure_agentcore_runtime(region, cognito_config)
        
        # Deploy and monitor
        launch_result = deploy_and_monitor_runtime(agentcore_runtime)
        
        # Store configuration for client access
        store_configuration(region, cognito_config, launch_result, username, password)
        
        # Success summary
        print("\n" + "=" * 60)
        print("🎉 Deployment completed successfully!")
        print(f"📍 Agent ARN: {launch_result.agent_arn}")
        print(f"🔑 Credentials stored in: {SECRETS_MANAGER_SECRET_NAME}")
        print(f"📋 Agent ARN stored in: {SSM_PARAMETER_NAME}")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Deployment failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

