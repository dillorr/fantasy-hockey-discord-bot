import difflib
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

# Shared HTTP session — reuses TCP connections and sends a browser UA on every request.
_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.80 Safari/537.36"
})

# Pre-compiled patterns for extracting data without a full HTML parse.
_JSON_SCRIPT_RE = re.compile(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', re.DOTALL)
_OG_TITLE_RE = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"')

# In-memory cache for line combinations: slug -> (result, expires_at).
_lines_cache: Dict[str, Tuple[str, datetime]] = {}
_LINES_CACHE_TTL = 900  # 15 minutes


def _extract_page_json(html: str) -> Optional[Any]:
    """Return parsed JSON from the first application/json script tag, without a full parse."""
    match = _JSON_SCRIPT_RE.search(html)
    if not match:
        return None
    return json.loads(match.group(1))


def _extract_og_title(html: str, default: str) -> str:
    """Return og:title meta content without a full HTML parse."""
    match = _OG_TITLE_RE.search(html)
    return match.group(1).strip() if match else default


# Maps Daily Faceoff URL slugs to lists of recognized aliases (team name, city, abbreviation, nicknames).
_NHL_TEAMS: Dict[str, List[str]] = {
    "anaheim-ducks":          ["anaheim", "ducks", "ana"],
    "boston-bruins":          ["boston", "bruins", "bos"],
    "buffalo-sabres":         ["buffalo", "sabres", "buf"],
    "calgary-flames":         ["calgary", "flames", "cgy"],
    "carolina-hurricanes":    ["carolina", "hurricanes", "canes", "car"],
    "chicago-blackhawks":     ["chicago", "blackhawks", "hawks", "chi"],
    "colorado-avalanche":     ["colorado", "avalanche", "avs", "col"],
    "columbus-blue-jackets":  ["columbus", "blue jackets", "jackets", "cbj"],
    "dallas-stars":           ["dallas", "stars", "dal"],
    "detroit-red-wings":      ["detroit", "red wings", "wings", "det"],
    "edmonton-oilers":        ["edmonton", "oilers", "edm"],
    "florida-panthers":       ["florida", "panthers", "fla"],
    "los-angeles-kings":      ["los angeles", "kings", "lak", "la kings", "la"],
    "minnesota-wild":         ["minnesota", "wild", "min"],
    "montreal-canadiens":     ["montreal", "canadiens", "habs", "mtl"],
    "nashville-predators":    ["nashville", "predators", "preds", "nsh"],
    "new-jersey-devils":      ["new jersey", "devils", "njd"],
    "new-york-islanders":     ["new york islanders", "islanders", "isles", "nyi"],
    "new-york-rangers":       ["new york rangers", "rangers", "nyr"],
    "ottawa-senators":        ["ottawa", "senators", "sens", "ott"],
    "philadelphia-flyers":    ["philadelphia", "flyers", "phi"],
    "pittsburgh-penguins":    ["pittsburgh", "penguins", "pens", "pit"],
    "san-jose-sharks":        ["san jose", "sharks", "sjs"],
    "seattle-kraken":         ["seattle", "kraken", "sea"],
    "st-louis-blues":         ["st louis", "st. louis", "blues", "stl"],
    "tampa-bay-lightning":    ["tampa bay", "tampa", "lightning", "bolts", "tbl"],
    "toronto-maple-leafs":    ["toronto", "maple leafs", "leafs", "tor"],
    "utah-hockey-club":       ["utah", "hockey club", "utah hc", "uta"],
    "vancouver-canucks":      ["vancouver", "canucks", "van"],
    "vegas-golden-knights":   ["vegas", "golden knights", "knights", "vgk", "las vegas"],
    "washington-capitals":    ["washington", "capitals", "caps", "wsh"],
    "winnipeg-jets":          ["winnipeg", "jets", "wpg"],
}

# Abbreviations for line combination group names.
_GROUP_ABBREV: Dict[str, str] = {
    "Line 1": "L1", "Line 2": "L2", "Line 3": "L3", "Line 4": "L4",
    "Power Play 1": "PP1", "Power Play 2": "PP2",
    "Defense Line 1": "D1", "Defense Line 2": "D2", "Defense Line 3": "D3",
    "Goalies": "G",
}

# Flat alias→slug lookup built once at import time.
_ALIAS_TO_SLUG: Dict[str, str] = {
    alias: slug
    for slug, aliases in _NHL_TEAMS.items()
    for alias in aliases
}


def resolve_team_slug(team_input: str) -> Optional[str]:
    """
    Resolve a user-supplied team name to a Daily Faceoff URL slug.

    Resolution order:
    1. Exact slug match (e.g. "san-jose-sharks")
    2. Exact alias match (e.g. "sharks", "sjs", "san jose")
    3. Substring match against aliases
    4. Fuzzy match via difflib (cutoff 0.7)

    Returns the slug string, or None if no match is found.
    """
    normalized = team_input.lower().strip()

    # 1. Direct slug
    if normalized in _NHL_TEAMS:
        return normalized
    hyphenated = normalized.replace(" ", "-")
    if hyphenated in _NHL_TEAMS:
        return hyphenated

    # 2. Exact alias
    if normalized in _ALIAS_TO_SLUG:
        return _ALIAS_TO_SLUG[normalized]

    # 3. Substring: user input contained in an alias, or alias contained in user input
    for alias, slug in _ALIAS_TO_SLUG.items():
        if normalized in alias or alias in normalized:
            return slug

    # 4. Fuzzy fallback
    matches = difflib.get_close_matches(normalized, _ALIAS_TO_SLUG.keys(), n=1, cutoff=0.7)
    if matches:
        return _ALIAS_TO_SLUG[matches[0]]

    return None


def get_injury_report() -> str:
    """Fetch and format the current NHL injury report from CBS Sports."""
    url = "https://www.cbssports.com/nhl/injuries/"

    response = _session.get(url, timeout=10)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")

    rows = soup.find_all("tr", class_="TableBase-bodyTr")
    injury_data: List[Dict[str, str]] = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) >= 5:
            name_span = cells[0].find("span", class_="CellPlayerName--long")
            player_name = name_span.text.strip() if name_span else cells[0].text.strip()
            injury_data.append({
                "name": player_name,
                "position": cells[1].text.strip(),
                "date": " ".join(cells[2].text.strip().split(" ")[1:]),
                "injury": cells[3].text.strip(),
                "details": cells[4].text.strip(),
            })

    today_date = datetime.now(ZoneInfo("America/Los_Angeles")).date().replace(year=1900)
    todays_injuries = [
        obj for obj in injury_data
        if datetime.strptime(obj["date"], "%b %d").date() == today_date
    ]
    todays_injuries.sort(key=lambda d: d["name"])

    return _format_injury_response(todays_injuries, url)


def _format_injury_response(injuries: List[Dict[str, str]], source_url: str) -> str:
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    date_str = f"{now.strftime('%b')} {now.day}"

    output = f"**☠️ Injury Report — {date_str}**\n"
    for injury in injuries:
        output += f"{injury['name']} ({injury['position']}) — {injury['injury']} — {injury['details']}\n"
    output += f"-# Source: <{source_url}>"

    if len(output) > 2000:
        output = f"**☠️ Injury Report — {date_str} (Condensed)**\n"
        output += "*Full report exceeds Discord limit — see source.*\n"
        for injury in injuries:
            output += f"{injury['name']} ({injury['position']}) — {injury['injury']}\n"
        output += f"-# Source: <{source_url}>"

    return output


def get_starting_goalies() -> str:
    """Fetch and format today's starting goalies from Daily Faceoff."""
    url = "https://www.dailyfaceoff.com/starting-goalies/"

    page = _session.get(url, timeout=10)
    page.raise_for_status()

    page_title = _extract_og_title(page.text, "Starting Goalies")

    try:
        data = _extract_page_json(page.text)
        if data is None:
            return "Error: Could not find starting goalie data"
        matchups = data["props"]["pageProps"]["data"]
    except (json.JSONDecodeError, KeyError):
        return "Error: Could not parse starting goalie data"

    return _format_goalies_response(matchups, page_title, url)


def _format_goalies_response(matchups: List[Dict[str, Any]], page_title: str, source_url: str) -> str:
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    date_str = f"{now.strftime('%b')} {now.day}"

    output = f"**🥅 Starting Goalies — {date_str}**\n"

    for matchup in matchups:
        home_team = matchup.get("homeTeamName", "Unknown")
        away_team = matchup.get("awayTeamName", "Unknown")
        game_time = matchup.get("time", "TBD")
        home_goalie = matchup.get("homeGoalieName", "TBD")
        away_goalie = matchup.get("awayGoalieName", "TBD")
        home_status = matchup.get("homeNewsStrengthName") or ""
        away_status = matchup.get("awayNewsStrengthName") or ""

        home_ind = "✓" if home_status and "confirmed" in home_status.lower() else "?"
        away_ind = "✓" if away_status and "confirmed" in away_status.lower() else "?"

        output += f"{away_team} @ {home_team} ({game_time}) — {away_goalie} {away_ind} vs {home_goalie} {home_ind}\n"

    footer = f"-# Source: <{source_url}>"
    if len(output) + len(footer) > 2000:
        output = output[:1900] + "\n*[truncated — see source for full matchups]*\n"
    output += footer
    return output


def get_line_combinations(team_name: str) -> str:
    """Fetch and format line combinations for a specific team from Daily Faceoff."""
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    cached = _lines_cache.get(team_name)
    if cached is not None:
        result, expires_at = cached
        if now < expires_at:
            return result

    url = f"https://www.dailyfaceoff.com/teams/{team_name}/line-combinations/"

    page = _session.get(url, timeout=10)
    page.raise_for_status()

    page_title = _extract_og_title(page.text, "Line Combinations")

    try:
        data = _extract_page_json(page.text)
        if data is None:
            return f"Error: Could not find line combination data for {team_name}"
        players = data["props"]["pageProps"]["combinations"]["players"]
    except (json.JSONDecodeError, KeyError):
        return f"Error: Could not parse line combination data for {team_name}"

    today = f"{now.strftime('%b')} {now.day}"
    result = _format_lines_response(players, page_title, today, url)
    _lines_cache[team_name] = (result, now + timedelta(seconds=_LINES_CACHE_TTL))
    return result


def _format_lines_response(players: List[Dict[str, Any]], page_title: str, date: str, source_url: str) -> str:
    # Strip "| Daily Faceoff" or similar suffixes from the og:title
    clean_title = re.sub(r'\s*\|.*$', '', page_title).strip()

    # Group players while preserving order
    groups: Dict[str, List[str]] = {}
    for player in players:
        group_name = player.get("groupName") or "Other"
        last_name = (player.get("name") or "Unknown").split()[-1]
        groups.setdefault(group_name, []).append(last_name)

    output = f"**🏒 {clean_title} — {date}**\n"
    for group_name, names in groups.items():
        abbrev = _GROUP_ABBREV.get(group_name, group_name)
        output += f"**{abbrev}:** {' · '.join(names)}\n"

    footer = f"-# Source: <{source_url}>"
    if len(output) + len(footer) > 2000:
        output = output[:1900] + "\n*[truncated — see source for full lines]*\n"
    output += footer
    return output
