"""LinkedIn profile enrichment via Firecrawl.

Scrapes LinkedIn profiles to extract work history, education, and other
PersonInfo fields. No Playwright, no cookies — Firecrawl handles anti-bot.

Flow:
  1. Check in-memory cache
  2. Find LinkedIn URL (slug guess → Bing → DDG → fallback)
  3. Scrape with Firecrawl → extract structured data
  4. Cache result
"""
import logging
import re
import urllib.parse
from typing import Optional, TypedDict

import httpx

from config import FIRECRAWL_API_KEY

logger = logging.getLogger("orbit.enrichment")

# In-memory enrichment cache (name → PersonInfo)
_cache: dict[str, dict] = {}

# User's LinkedIn connections (populated after OAuth — kept for future use)
_user_connections: list[str] = []
_linkedin_cookies: list[dict] = []


class PersonInfo(TypedDict, total=False):
    """Structured profile data matching the frontend's PersonInfo interface."""
    age: int
    sex: str
    pronouns: str
    occupation: str
    work: list[str]          # ["Company — Role (Years)"]
    education: list[str]     # ["School — Degree"]
    note: str                # Key insight about this person
    mutualConnections: list[str]
    connectionSource: str
    linkedinUrl: str


def set_user_connections(connections: list[str]):
    global _user_connections
    _user_connections = connections
    logger.info(f"Stored {len(connections)} user LinkedIn connections")


def set_linkedin_cookies(cookies: list[dict]):
    global _linkedin_cookies
    _linkedin_cookies = cookies
    logger.info("Stored LinkedIn session cookies")


async def enrich_person(name: str, linkedin_url: Optional[str] = None) -> Optional[dict]:
    """Enrich a person's profile from LinkedIn.

    Args:
        name: Full name (e.g. "Alex Chen")
        linkedin_url: Optional CONFIRMED LinkedIn URL (user provided or stored)

    Returns:
        PersonInfo dict or None if enrichment fails.

    LinkedIn URL logic:
      - If linkedin_url is explicitly provided (user confirmed) → use it directly
      - Otherwise → always use the LinkedIn SEARCH page so the user can pick
        the right person themselves (avoids linking to wrong profiles)
    """
    cache_key = name.lower().strip()

    # 1. Check cache
    if cache_key in _cache:
        logger.info(f"Enrichment cache hit: {name}")
        return _cache[cache_key]

    # 2. Determine LinkedIn URL
    search_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(name)}"

    if linkedin_url and "/in/" in linkedin_url:
        # User explicitly confirmed this URL — trust it, try to scrape
        profile_url = linkedin_url
        info: dict = {}

        # Try Firecrawl scrape on confirmed URL
        if FIRECRAWL_API_KEY:
            try:
                info = await _firecrawl_scrape(profile_url)
                if info:
                    logger.info(f"Firecrawl scraped {name}: {list(info.keys())}")
            except Exception as e:
                logger.warning(f"Firecrawl scrape failed for {name}: {e}")

        # Fall back to public meta tag extraction
        if not info.get("occupation"):
            try:
                meta_info = await _fetch_public_meta(profile_url)
                if meta_info:
                    for k, v in meta_info.items():
                        info.setdefault(k, v)
            except Exception as e:
                logger.warning(f"Public meta fetch failed for {name}: {e}")

        info["linkedinUrl"] = profile_url
        info.setdefault("connectionSource", "LinkedIn")
        _cache[cache_key] = info
        return info
    else:
        # No confirmed URL — link to search so user finds the right person
        info = {"linkedinUrl": search_url, "connectionSource": "LinkedIn Search"}
        _cache[cache_key] = info
        return info


async def _firecrawl_scrape(url: str) -> dict:
    """Scrape a LinkedIn profile using Firecrawl API.

    Firecrawl handles JS rendering, anti-bot, and returns clean markdown.
    We parse the markdown to extract structured PersonInfo fields.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "url": url,
                "formats": ["markdown"],
                "waitFor": 3000,
            },
            timeout=30.0,
        )
        if resp.status_code != 200:
            body = resp.text[:300]
            logger.warning(f"Firecrawl scrape {resp.status_code}: {body}")
            return {}
        data = resp.json()

    md = data.get("data", {}).get("markdown", "")
    metadata = data.get("data", {}).get("metadata", {})

    if not md:
        logger.warning(f"Firecrawl returned empty markdown for {url}")
        return {}

    info: dict = {"linkedinUrl": url, "connectionSource": "LinkedIn"}

    # Extract from metadata (title tag)
    title = metadata.get("title", "")
    if title:
        # "Alex Chen - Senior Engineer - Vercel | LinkedIn"
        parts = title.replace(" | LinkedIn", "").split(" - ")
        if len(parts) >= 2:
            info["occupation"] = parts[1].strip()

    og_desc = metadata.get("description", "") or metadata.get("og:description", "")
    if og_desc and len(og_desc) > 20:
        info["note"] = og_desc[:200]

    # Parse markdown for structured sections
    info.update(_parse_linkedin_markdown(md))

    return info


async def _fetch_public_meta(url: str) -> dict:
    """Extract basic info from LinkedIn's public meta tags (no auth needed).

    LinkedIn profile pages include og:title, og:description, and title tags
    with occupation info even without login.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html",
        "Accept-Language": "en-US,en;q=0.9",
    }
    info: dict = {}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url, headers=headers, timeout=10.0)
        if resp.status_code != 200:
            return info
        text = resp.text

        # <title>Name - Title - Company | LinkedIn</title>
        title_match = re.search(r"<title>([^<]+)</title>", text)
        if title_match:
            title = title_match.group(1).replace(" | LinkedIn", "")
            parts = title.split(" - ")
            if len(parts) >= 2:
                info["occupation"] = parts[1].strip()
            if len(parts) >= 3:
                info.setdefault("work", []).append(parts[2].strip())

        # og:description or description meta — often has a summary
        for pattern in [
            r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
            r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
        ]:
            desc_match = re.search(pattern, text)
            if desc_match:
                desc = desc_match.group(1).strip()
                if len(desc) > 20:
                    info["note"] = desc[:200]
                break

    return info


def _parse_linkedin_markdown(md: str) -> dict:
    """Parse Firecrawl's markdown output from a LinkedIn profile.

    LinkedIn profiles in markdown typically have sections like:
    ## Experience / ## Education with bullet points.
    """
    info: dict = {}
    lines = md.split("\n")

    current_section = ""
    work_items: list[str] = []
    education_items: list[str] = []

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        # Detect section headers
        if stripped.startswith("#"):
            header = stripped.lstrip("#").strip().lower()
            if "experience" in header:
                current_section = "experience"
            elif "education" in header:
                current_section = "education"
            elif "about" in header:
                current_section = "about"
            else:
                current_section = header
            continue

        if not stripped:
            continue

        # Extract content per section
        if current_section == "experience":
            # Work items — look for company/role patterns
            if stripped.startswith(("- ", "* ", "• ")) or (len(stripped) > 5 and not stripped.startswith("[")):
                clean = stripped.lstrip("-*• ").strip()
                if clean and len(clean) > 3 and not clean.startswith("http"):
                    work_items.append(clean)

        elif current_section == "education":
            if stripped.startswith(("- ", "* ", "• ")) or (len(stripped) > 5 and not stripped.startswith("[")):
                clean = stripped.lstrip("-*• ").strip()
                if clean and len(clean) > 3 and not clean.startswith("http"):
                    education_items.append(clean)

        elif current_section == "about":
            if stripped and not stripped.startswith("#") and len(stripped) > 10:
                info.setdefault("note", stripped[:200])

    # Deduplicate and limit
    if work_items:
        seen = set()
        unique_work = []
        for w in work_items:
            key = w.lower()[:30]
            if key not in seen:
                seen.add(key)
                unique_work.append(w)
        info["work"] = unique_work[:5]

    if education_items:
        seen = set()
        unique_edu = []
        for e in education_items:
            key = e.lower()[:30]
            if key not in seen:
                seen.add(key)
                unique_edu.append(e)
        info["education"] = unique_edu[:3]

    # Try to extract headline/occupation from first few lines
    if "occupation" not in info:
        for line in lines[:15]:
            stripped = line.strip()
            # LinkedIn headlines are usually short, non-link lines near the top
            if (10 < len(stripped) < 100
                and not stripped.startswith(("#", "[", "!", "http"))
                and any(kw in stripped.lower() for kw in ["engineer", "manager", "director", "founder",
                        "analyst", "designer", "scientist", "developer", "lead", "head", "vp",
                        "ceo", "cto", "coo", "intern", "student", "professor", "consultant",
                        "architect", "partner", "associate", "specialist", "coordinator"])):
                info["occupation"] = stripped
                break

    return info


async def _find_linkedin_url(name: str) -> Optional[str]:
    """Find a person's LinkedIn profile URL.

    Strategy:
      1. Firecrawl search (if API key available)
      2. Guess common slug patterns + HEAD-check
      3. Bing search
      4. DuckDuckGo search
      5. Fallback: LinkedIn search URL
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # ── Strategy 1: Firecrawl search ──
    if FIRECRAWL_API_KEY:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.firecrawl.dev/v1/search",
                    headers={
                        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": f"{name} site:linkedin.com/in/",
                        "limit": 3,
                    },
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    results = resp.json().get("data", [])
                    for r in results:
                        url = r.get("url", "")
                        if "linkedin.com/in/" in url:
                            profile_url = url.rstrip("/")
                            logger.info(f"Firecrawl search found LinkedIn for {name}: {profile_url}")
                            return profile_url
        except Exception as e:
            logger.warning(f"Firecrawl search failed: {e}")

    # ── Strategy 2: Guess common LinkedIn slug patterns ──
    parts = name.lower().strip().split()
    if len(parts) >= 2:
        guesses = [
            f"{parts[0]}-{parts[-1]}",
            f"{parts[0]}{parts[-1]}",
            f"{'-'.join(parts)}",
        ]
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for slug in guesses:
                url = f"https://www.linkedin.com/in/{slug}"
                try:
                    resp = await client.head(url, headers=headers, timeout=5.0)
                    if resp.status_code == 200 and "/in/" in str(resp.url):
                        logger.info(f"LinkedIn slug guess hit: {url}")
                        return url
                except Exception:
                    continue

    # ── Strategy 3: Bing ──
    query = f"{name} site:linkedin.com/in/"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://www.bing.com/search?q={urllib.parse.quote(query)}&count=5",
                headers=headers, timeout=8.0, follow_redirects=True,
            )
            if resp.status_code == 200:
                matches = re.findall(
                    r"https?://(?:\w+\.)?linkedin\.com/in/[a-zA-Z0-9_-]+/?",
                    resp.text,
                )
                if matches:
                    profile_url = matches[0].rstrip("/")
                    logger.info(f"Bing found LinkedIn for {name}: {profile_url}")
                    return profile_url
    except Exception as e:
        logger.warning(f"Bing search failed: {e}")

    # ── Strategy 4: DuckDuckGo ──
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}",
                headers=headers, timeout=8.0, follow_redirects=True,
            )
            if resp.status_code == 200:
                matches = re.findall(
                    r"https?://(?:\w+\.)?linkedin\.com/in/[a-zA-Z0-9_-]+/?",
                    resp.text,
                )
                if matches:
                    profile_url = matches[0].rstrip("/")
                    logger.info(f"DDG found LinkedIn for {name}: {profile_url}")
                    return profile_url
    except Exception as e:
        logger.warning(f"DDG search failed: {e}")

    # ── Fallback ──
    fallback = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(name)}"
    logger.info(f"Using LinkedIn search fallback for {name}")
    return fallback


def get_cached_info(name: str) -> Optional[dict]:
    return _cache.get(name.lower().strip())


def clear_cache():
    _cache.clear()
    logger.info("Enrichment cache cleared")
