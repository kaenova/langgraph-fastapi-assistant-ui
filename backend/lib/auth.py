"""Authentication utilities for the FastAPI server."""
import os
import secrets
from typing import Annotated
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize HTTP Basic Auth
security = HTTPBasic(auto_error=False)

# Get credentials from environment
BACKEND_AUTH_USERNAME = os.getenv("BACKEND_AUTH_USERNAME", "apiuser")
BACKEND_AUTH_PASSWORD = os.getenv("BACKEND_AUTH_PASSWORD", "securepass123")


def verify_credentials(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> str:
    """
    Verify HTTP Basic Auth credentials.
    
    Args:
        credentials: HTTP Basic Auth credentials
        
    Returns:
        str: Username if authentication is successful
        
    Raises:
        HTTPException: If authentication fails
    """
    print("🔐 Verifying credentials for user:", credentials.username)
    print("   Provided password length:", len(credentials.password) * "*")

    # Use secrets.compare_digest to prevent timing attacks
    is_correct_username = secrets.compare_digest(
        credentials.username.encode("utf-8"), 
        BACKEND_AUTH_USERNAME.encode("utf-8")
    )
    is_correct_password = secrets.compare_digest(
        credentials.password.encode("utf-8"), 
        BACKEND_AUTH_PASSWORD.encode("utf-8")
    )
    
    if not (is_correct_username and is_correct_password):
        print("❌ Authentication failed for user:", credentials.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    return credentials.username


# Dependency that can be used in route handlers
def get_authenticated_user(username: Annotated[str, Depends(verify_credentials)]) -> str:
    """
    Dependency that ensures the user is authenticated.
    
    Args:
        username: Username from successful authentication
        
    Returns:
        str: Authenticated username
    """
    return username