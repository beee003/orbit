"""LinkedIn OAuth 2.0 authentication flow.

Provides endpoints for:
  1. Redirecting users to LinkedIn's OAuth consent screen
  2. Handling the callback with authorization code → access token
  3. Fetching the user's profile

LinkedIn OAuth docs: https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow

Required scopes:
  - openid          — basic profile info
  - profile         — name, headline, picture
  - email           — email address
"""
import logging
import secrets
from typing import Optional

import httpx

from config import (
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI,
)
logger = logging.getLogger("orbit.linkedin_auth")

# In-memory session storage (hackathon-grade — use Redis/DB in production)
_oauth_states: dict[str, bool] = {}  # state → True (pending)
_access_tokens: dict[str, str] = {}  # user_id → access_token
_user_profiles: dict[str, dict] = {}  # user_id → LinkedIn profile

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_PROFILE_URL = "https://api.linkedin.com/v2/userinfo"


def get_auth_url() -> str:
    """Generate LinkedIn OAuth 2.0 authorization URL.

    Returns:
        URL to redirect the user to for LinkedIn login.
    """
    state = secrets.token_urlsafe(16)
    _oauth_states[state] = True

    params = {
        "response_type": "code",
        "client_id": LINKEDIN_CLIENT_ID,
        "redirect_uri": LINKEDIN_REDIRECT_URI,
        "scope": "openid profile email",
        "state": state,
    }

    query = "&".join(f"{k}={httpx.URL('', params={k: v}).params[k]}" for k, v in params.items())
    url = f"{LINKEDIN_AUTH_URL}?{query}"
    logger.info(f"Generated LinkedIn OAuth URL (state={state[:8]}...)")
    return url


async def handle_callback(code: str, state: str) -> Optional[dict]:
    """Handle LinkedIn OAuth callback — exchange code for token.

    Args:
        code: Authorization code from LinkedIn
        state: State parameter (CSRF protection)

    Returns:
        User profile dict or None on failure.
    """
    # Verify state to prevent CSRF
    if state not in _oauth_states:
        logger.warning(f"Invalid OAuth state: {state[:8]}...")
        return None
    del _oauth_states[state]

    # Exchange authorization code for access token
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                LINKEDIN_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": LINKEDIN_REDIRECT_URI,
                    "client_id": LINKEDIN_CLIENT_ID,
                    "client_secret": LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10.0,
            )
            resp.raise_for_status()
            token_data = resp.json()
        except Exception as e:
            logger.error(f"LinkedIn token exchange failed: {e}")
            return None

        access_token = token_data.get("access_token")
        if not access_token:
            logger.error(f"No access_token in response: {token_data}")
            return None

        logger.info("LinkedIn OAuth token obtained successfully")

        # Fetch user profile (reuse same client)
        try:
            profile = await _fetch_profile(client, access_token)
        except Exception as e:
            logger.error(f"LinkedIn profile fetch failed: {e}")
            profile = {}

    # Store token and profile
    user_id = profile.get("sub", "linkedin_user")
    _access_tokens[user_id] = access_token
    _user_profiles[user_id] = profile

    # Connections scraping removed — too heavy for demo.
    # Mutual connections can be added post-hackathon via LinkedIn API approval.

    return {
        "user_id": user_id,
        "name": profile.get("name", ""),
        "email": profile.get("email", ""),
        "picture": profile.get("picture", ""),
    }


async def _fetch_profile(client: httpx.AsyncClient, token: str) -> dict:
    """Fetch the authenticated user's LinkedIn profile via API.

    Uses the OpenID Connect userinfo endpoint.
    """
    resp = await client.get(
        LINKEDIN_PROFILE_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.info(f"LinkedIn profile: {data.get('name', 'unknown')}")
    return data


def get_access_token(user_id: str = "linkedin_user") -> Optional[str]:
    """Get stored access token for a user."""
    return _access_tokens.get(user_id)


def is_authenticated() -> bool:
    """Check if any LinkedIn account is authenticated."""
    return len(_access_tokens) > 0
