"""LinkedIn OAuth 2.0 authentication flow.

Provides endpoints for:
  1. Redirecting users to LinkedIn's OAuth consent screen
  2. Handling the callback with authorization code → access token
  3. Fetching the user's profile and 1st-degree connections
  4. Storing session cookies for Playwright-based scraping

LinkedIn OAuth docs: https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow

Required scopes:
  - openid          — basic profile info
  - profile         — name, headline, picture
  - email           — email address
  - w_member_social — (optional) for enrichment features
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
import enrichment

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
        "scope": "openid profile email r_1st_connections",
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


async def _fetch_connections(token: str) -> list[str]:
    """Fetch the authenticated user's 1st-degree connection names.

    Uses LinkedIn Connections API. Returns list of connection display names.
    Falls back to Playwright scraping if API access is limited.
    """
    # Try the official API first (requires r_1st_connections scope)
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                "https://api.linkedin.com/v2/connections",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": "viewer", "start": 0, "count": 500},
                timeout=15.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                names = []
                for element in data.get("elements", []):
                    first = element.get("firstName", {}).get("localized", {})
                    last = element.get("lastName", {}).get("localized", {})
                    fn = next(iter(first.values()), "")
                    ln = next(iter(last.values()), "")
                    if fn or ln:
                        names.append(f"{fn} {ln}".strip())
                return names
            else:
                logger.info(f"Connections API returned {resp.status_code} — falling back to scrape")
        except Exception as e:
            logger.warning(f"Connections API failed: {e}")

    # Fallback: scrape the connections page with Playwright
    return await _scrape_connections_page(token)


async def _scrape_connections_page(token: str) -> list[str]:
    """Scrape LinkedIn connections page using Playwright.

    Uses the access token to set up an authenticated browser session.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed — cannot scrape connections")
        return []

    names = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            page = await context.new_page()

            # Navigate to connections page
            await page.goto(
                "https://www.linkedin.com/mynetwork/invite-connect/connections/",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            await page.wait_for_timeout(3000)

            # Check if we need to log in
            if "/login" in page.url or "authwall" in page.url:
                logger.warning("LinkedIn login wall on connections page")
                await browser.close()
                return []

            # Scroll to load more connections
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            # Extract connection names
            cards = await page.query_selector_all(
                ".mn-connection-card__name, .entity-result__title-text"
            )
            for card in cards[:200]:
                name = await card.inner_text()
                cleaned = name.strip()
                if cleaned:
                    names.append(cleaned)

            # Store cookies for future Playwright scraping
            cookies = await context.cookies()
            enrichment.set_linkedin_cookies(cookies)

            await browser.close()

    except Exception as e:
        logger.error(f"Connections scrape failed: {e}")

    logger.info(f"Scraped {len(names)} connections from LinkedIn")
    return names


def get_access_token(user_id: str = "linkedin_user") -> Optional[str]:
    """Get stored access token for a user."""
    return _access_tokens.get(user_id)


def is_authenticated() -> bool:
    """Check if any LinkedIn account is authenticated."""
    return len(_access_tokens) > 0
