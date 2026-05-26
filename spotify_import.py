"""
Spotify playlist import module for the Discord music bot.

Reads a public Spotify playlist, matches each track to YouTube via
YouTube Music search, and scores matches by title/artist/duration similarity.

Required packages (add to requirements.txt when enabling):
    spotipy>=2.24.0,<3.0
    ytmusicapi>=1.8.0,<2.0
    rapidfuzz>=3.0.0,<4.0

Environment variables:
    SPOTIFY_CLIENT_ID      – Spotify Developer app client ID
    SPOTIFY_CLIENT_SECRET  – Spotify Developer app client secret
    SPOTIFY_ENABLED        – set to true/1/yes to activate the module

Activation:
    Set SPOTIFY_ENABLED=true in .env and restart the bot.
    The /spotify commands will appear on the next sync.
"""

import os
import re
import time
import asyncio
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# Confidence thresholds
CONFIDENCE_AUTO = 0.82      # auto-import without asking
CONFIDENCE_REVIEW = 0.50    # show in review; below this, skip unless confirmed
CONFIDENCE_FLOOR = 0.30     # discard entirely below this

YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v="
MAX_YTM_RESULTS = 5         # candidates per track from YouTube Music
SPOTIFY_PAGE_SIZE = 100     # max items per Spotify page request

# Review message controls
REVIEW_EMOJI_ACCEPT   = "👍"
REVIEW_EMOJI_SKIP     = "👎"
REVIEW_EMOJI_ALT      = "🔄"
REVIEW_EMOJI_SKIP_ALL = "⏭️"
REVIEW_EMOJI_ACCEPT_ALL  = "✅"
REVIEW_EMOJI_SKIP_UNCERTAIN = "🚫"
REVIEW_EMOJI_STEP_REVIEW = "🔍"

REVIEW_SUMMARY_EMOJIS = (
    REVIEW_EMOJI_ACCEPT_ALL,
    REVIEW_EMOJI_SKIP_UNCERTAIN,
    REVIEW_EMOJI_STEP_REVIEW,
)
REVIEW_TRACK_EMOJIS = (
    REVIEW_EMOJI_ACCEPT,
    REVIEW_EMOJI_SKIP,
    REVIEW_EMOJI_ALT,
    REVIEW_EMOJI_SKIP_ALL,
)

IMPORT_TTL_SECONDS = 600    # pending imports expire after 10 minutes of inactivity

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

def check_dependencies() -> list:
    """Return a list of missing package names that need to be installed."""
    missing = []
    for pkg, spec in (
        ("spotipy", "spotipy>=2.24.0,<3.0"),
        ("ytmusicapi", "ytmusicapi>=1.8.0,<2.0"),
    ):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(spec)
    return missing

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SpotifyTrack:
    name: str
    artists: list
    album: str
    duration_ms: int
    spotify_uri: str
    track_number: int

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else ""

    @property
    def all_artists(self) -> str:
        return ", ".join(self.artists[:3])

    @property
    def search_query(self) -> str:
        return f"{self.name} {self.primary_artist}"

    @property
    def duration_seconds(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def duration_display(self) -> str:
        s = int(self.duration_seconds)
        return f"{s // 60}:{s % 60:02d}"

    @property
    def display(self) -> str:
        return f"**{self.name}** · {self.all_artists}"


@dataclass
class YouTubeMatch:
    video_id: str
    title: str
    channel: str
    duration_seconds: Optional[float]
    confidence: float
    source: str = "ytmusicapi"

    @property
    def url(self) -> str:
        return YOUTUBE_WATCH_URL + self.video_id

    @property
    def short_url(self) -> str:
        return f"youtu.be/{self.video_id}"

    @property
    def duration_display(self) -> str:
        if self.duration_seconds is None:
            return "?:??"
        s = int(self.duration_seconds)
        return f"{s // 60}:{s % 60:02d}"

    @property
    def confidence_emoji(self) -> str:
        if self.confidence >= CONFIDENCE_AUTO:
            return "🟢"
        if self.confidence >= CONFIDENCE_REVIEW:
            return "🟡"
        return "🔴"

    @property
    def confidence_pct(self) -> str:
        return f"{int(self.confidence * 100)}%"


@dataclass
class PendingTrack:
    spotify: SpotifyTrack
    best_match: Optional[YouTubeMatch]
    alternatives: list = field(default_factory=list)   # list[YouTubeMatch]
    status: str = "pending"   # "auto" | "accepted" | "rejected" | "no_match"
    alt_index: int = 0        # which alternative is currently displayed in review

    @property
    def active_match(self) -> Optional[YouTubeMatch]:
        """The match currently shown in the per-track review."""
        if self.alt_index == 0:
            return self.best_match
        idx = self.alt_index - 1
        return self.alternatives[idx] if idx < len(self.alternatives) else self.best_match

    def advance_alternative(self):
        """Cycle to the next alternative match."""
        total = 1 + len(self.alternatives)  # best + alternatives
        self.alt_index = (self.alt_index + 1) % total


@dataclass
class PendingImport:
    import_id: str
    playlist_name: str
    spotify_url: str
    requested_by_user_id: int
    created_at: float
    tracks: list = field(default_factory=list)   # list[PendingTrack]
    playlist_id: Optional[str] = None
    review_message_id: Optional[int] = None
    review_index: int = 0     # current position in per-track review (index into pending_tracks)
    last_touched: float = field(default_factory=time.time)

    @property
    def auto_tracks(self) -> list:
        return [t for t in self.tracks if t.status == "auto"]

    @property
    def pending_tracks(self) -> list:
        return [t for t in self.tracks if t.status == "pending"]

    @property
    def no_match_tracks(self) -> list:
        return [t for t in self.tracks if t.status == "no_match"]

    @property
    def accepted_tracks(self) -> list:
        return [t for t in self.tracks if t.status in ("auto", "accepted")]

    @property
    def rejected_tracks(self) -> list:
        return [t for t in self.tracks if t.status == "rejected"]

    def is_expired(self) -> bool:
        return time.time() - self.last_touched > IMPORT_TTL_SECONDS

    def touch(self):
        self.last_touched = time.time()


# ---------------------------------------------------------------------------
# Text normalization and confidence scoring
# ---------------------------------------------------------------------------

_FEAT_PATTERN = re.compile(
    r"\s*[\(\[]\s*(feat\.?|ft\.?|with|prod\.?|official|video|audio|lyrics?|hd|4k|mv|music\s*video|topic).*?[\)\]]",
    re.IGNORECASE,
)
_SUFFIX_PATTERN = re.compile(
    r"\s*[-–—]\s*(official\s*(video|audio|music\s*video|lyric\s*video)|audio|lyrics?|hd|4k|full\s*(album|version))$",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Lowercase, strip accents, remove noise annotations, collapse whitespace."""
    text = str(text or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _FEAT_PATTERN.sub("", text)
    text = _SUFFIX_PATTERN.sub("", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _fuzzy_ratio(a: str, b: str) -> float:
    """Token-sort fuzzy ratio, 0.0–1.0. Falls back to difflib if rapidfuzz missing."""
    try:
        from rapidfuzz import fuzz
        sort = fuzz.token_sort_ratio(a, b) / 100
        partial = fuzz.partial_ratio(a, b) / 100
        wratio = fuzz.WRatio(a, b) / 100
        return max(sort, partial * 0.9, wratio * 0.95)
    except ImportError:
        import difflib
        return difflib.SequenceMatcher(None, a, b).ratio()


def _title_score(spotify_name: str, yt_title: str) -> float:
    return _fuzzy_ratio(_normalize(spotify_name), _normalize(yt_title))


def _artist_score(spotify_artist: str, yt_channel: str, yt_artists: Optional[list] = None) -> float:
    norm_spotify = _normalize(spotify_artist)
    candidates = [_normalize(yt_channel)]
    if yt_artists:
        candidates.extend(_normalize(a) for a in yt_artists)
    scores = [_fuzzy_ratio(norm_spotify, c) for c in candidates if c]
    return max(scores) if scores else 0.0


def _duration_score(spotify_secs: float, yt_secs: Optional[float]) -> float:
    if yt_secs is None or spotify_secs <= 0:
        return 0.50   # neutral — unknown duration
    diff = abs(spotify_secs - yt_secs)
    if diff <= 3:    return 1.00
    if diff <= 10:   return 0.85
    if diff <= 20:   return 0.65
    if diff <= 45:   return 0.35
    return max(0.0, 1.0 - diff / 120)


def confidence_score(spotify: SpotifyTrack, yt: dict, *, source: str = "ytmusicapi") -> float:
    """
    Score how well a YouTube search result matches a Spotify track.

    Weights:
      title    40 %
      artist   30 %
      duration 20 %
      type/src 10 %

    Returns a float in [0.0, 1.0].
    """
    yt_title = yt.get("title", "")
    yt_channel = yt.get("channel", "")
    if not yt_channel and yt.get("artists"):
        yt_channel = yt["artists"][0].get("name", "")
    yt_artist_names = [a.get("name", "") for a in yt.get("artists", [])]
    yt_duration = yt.get("duration_seconds")

    title_s    = _title_score(spotify.name, yt_title)
    artist_s   = _artist_score(spotify.primary_artist, yt_channel, yt_artist_names)
    duration_s = _duration_score(spotify.duration_seconds, yt_duration)

    result_type = str(yt.get("resultType", "")).lower()
    if result_type == "song":
        type_bonus = 0.10   # YouTube Music song result — most likely official
    elif source == "ytmusicapi":
        type_bonus = 0.05
    else:
        type_bonus = 0.00

    score = 0.40 * title_s + 0.30 * artist_s + 0.20 * duration_s + type_bonus
    return min(1.0, score)


# ---------------------------------------------------------------------------
# Spotify client
# ---------------------------------------------------------------------------

def _make_spotify_client():
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        raise ValueError(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in .env. "
            "Get them from https://developer.spotify.com/dashboard"
        )
    auth = SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    )
    return spotipy.Spotify(auth_manager=auth)


def extract_spotify_playlist_id(url: str) -> Optional[str]:
    """Extract the Spotify playlist ID from a URL, URI, or bare ID."""
    url = str(url or "").strip()
    m = re.match(r"spotify:playlist:([A-Za-z0-9]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"open\.spotify\.com/playlist/([A-Za-z0-9]+)", url)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z0-9]{22}$", url):
        return url
    return None


def _fetch_spotify_tracks_sync(playlist_url: str):
    """
    Synchronous: fetch all tracks and the playlist name from Spotify.
    Returns (playlist_name: str, tracks: list[SpotifyTrack]).
    """
    sp = _make_spotify_client()
    playlist_id = extract_spotify_playlist_id(playlist_url)
    if not playlist_id:
        raise ValueError(f"Cannot extract a Spotify playlist ID from: {playlist_url!r}")

    meta = sp.playlist(playlist_id, fields="name,tracks.total")
    playlist_name = meta.get("name") or "Spotify Playlist"

    tracks = []
    offset = 0
    while True:
        resp = sp.playlist_tracks(
            playlist_id,
            offset=offset,
            limit=SPOTIFY_PAGE_SIZE,
            fields="items(track(name,artists(name),album(name),duration_ms,uri,track_number)),next",
        )
        for item in resp.get("items", []):
            t = item.get("track")
            if not t or not t.get("name"):
                continue   # skip null entries and podcast episodes
            artists = [a["name"] for a in t.get("artists", []) if a.get("name")]
            tracks.append(SpotifyTrack(
                name=str(t["name"]),
                artists=artists,
                album=str((t.get("album") or {}).get("name", "")),
                duration_ms=int(t.get("duration_ms") or 0),
                spotify_uri=str(t.get("uri") or ""),
                track_number=int(t.get("track_number") or 0),
            ))
        if not resp.get("next"):
            break
        offset += SPOTIFY_PAGE_SIZE

    return playlist_name, tracks


# ---------------------------------------------------------------------------
# YouTube Music search
# ---------------------------------------------------------------------------

def _search_ytmusic_sync(query: str) -> list:
    """Search YouTube Music for songs. Returns a list of raw result dicts."""
    from ytmusicapi import YTMusic
    ytm = YTMusic()
    results = ytm.search(query, filter="songs", limit=MAX_YTM_RESULTS) or []
    if not results:
        # Broaden search if the filtered search came up empty
        results = ytm.search(query, limit=MAX_YTM_RESULTS) or []
    return results


def _parse_duration(raw) -> Optional[float]:
    """Parse a ytmusicapi duration string like '3:45' to seconds."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    parts = str(raw).split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, TypeError):
        pass
    return None


def _normalize_ytm_result(r: dict) -> dict:
    """Flatten a ytmusicapi result into the shape confidence_score expects."""
    artists = r.get("artists") or []
    channel = artists[0].get("name", "") if artists else r.get("channel", "")
    duration_seconds = _parse_duration(r.get("duration_seconds") or r.get("duration"))
    return {
        "video_id":       r.get("videoId", ""),
        "title":          r.get("title", ""),
        "channel":        channel,
        "artists":        artists,
        "duration_seconds": duration_seconds,
        "resultType":     r.get("resultType", ""),
        "album":          (r.get("album") or {}).get("name", ""),
    }


# ---------------------------------------------------------------------------
# Async public API
# ---------------------------------------------------------------------------

async def fetch_spotify_tracks(playlist_url: str):
    """Async wrapper around _fetch_spotify_tracks_sync."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_spotify_tracks_sync, playlist_url)


async def search_youtube_for_track(spotify_track: SpotifyTrack) -> list:
    """
    Search YouTube Music for a Spotify track and return a scored list of
    YouTubeMatch objects (best match first).  Returns [] if ytmusicapi fails.
    """
    loop = asyncio.get_event_loop()
    query = spotify_track.search_query
    try:
        raw_results = await loop.run_in_executor(None, _search_ytmusic_sync, query)
    except Exception as exc:
        logger.warning(f"YTMusic search failed for {query!r}: {exc}")
        return []

    matches = []
    for r in raw_results:
        norm = _normalize_ytm_result(r)
        if not norm["video_id"]:
            continue
        score = confidence_score(spotify_track, norm, source="ytmusicapi")
        if score < CONFIDENCE_FLOOR:
            continue
        matches.append(YouTubeMatch(
            video_id=norm["video_id"],
            title=norm["title"],
            channel=norm["channel"],
            duration_seconds=norm.get("duration_seconds"),
            confidence=score,
            source="ytmusicapi",
        ))
    matches.sort(key=lambda m: m.confidence, reverse=True)
    return matches


async def process_spotify_playlist(
    playlist_url: str,
    name_override: Optional[str] = None,
    *,
    requested_by_user_id: int = 0,
    progress_callback=None,   # async (done: int, total: int, label: str) -> None
) -> PendingImport:
    """
    Full pipeline: fetch Spotify tracks → match each to YouTube → categorize.
    Returns a PendingImport ready for review or commit.
    """
    import base64
    import secrets as _secrets

    playlist_name, spotify_tracks = await fetch_spotify_tracks(playlist_url)
    name = str(name_override or playlist_name or "Spotify Playlist").strip()
    total = len(spotify_tracks)

    import_id = base64.urlsafe_b64encode(_secrets.token_bytes(6)).decode("ascii").rstrip("=")
    pending = PendingImport(
        import_id=import_id,
        playlist_name=name,
        spotify_url=playlist_url,
        requested_by_user_id=requested_by_user_id,
        created_at=time.time(),
    )

    for i, sp_track in enumerate(spotify_tracks):
        if progress_callback:
            await progress_callback(i, total, sp_track.name[:50])

        matches = await search_youtube_for_track(sp_track)
        best = matches[0] if matches else None

        if best is None:
            status = "no_match"
        elif best.confidence >= CONFIDENCE_AUTO:
            status = "auto"
        else:
            status = "pending"

        pending.tracks.append(PendingTrack(
            spotify=sp_track,
            best_match=best,
            alternatives=matches[1:4],
            status=status,
        ))

    logger.info(
        f"Spotify import {import_id!r} '{name}': {total} tracks, "
        f"{len(pending.auto_tracks)} auto, "
        f"{len(pending.pending_tracks)} pending review, "
        f"{len(pending.no_match_tracks)} no match."
    )
    return pending


# ---------------------------------------------------------------------------
# Playlist entry helpers (called from main.py with user_id/user_name)
# ---------------------------------------------------------------------------

def make_playlist_entry(pt: PendingTrack, *, user_id: int = 0, user_name: str = "") -> Optional[dict]:
    """
    Convert a PendingTrack into a bot playlist metadata dict.
    Returns None if the track was rejected.
    """
    if pt.status not in ("auto", "accepted"):
        return None
    m = pt.active_match if pt.status == "accepted" else pt.best_match
    if m:
        yt_url = m.url
        video_id = m.video_id
        title = m.title or pt.spotify.name
        confidence = m.confidence
    else:
        # No YouTube match — store a yt-dlp search query; resolves at playback
        yt_url = f"ytsearch1:{pt.spotify.name} {pt.spotify.primary_artist}"
        video_id = ""
        title = f"{pt.spotify.name} — {pt.spotify.primary_artist}"
        confidence = 0.0
    return {
        "id":                       video_id,
        "title":                    title,
        "webpage_url":              yt_url,
        "needs_refresh":            not bool(video_id),
        "added_by_user_id":         user_id,
        "added_by_discord_name":    user_name,
        "added_at":                 time.time(),
        "cache_key":                None,
        "cache_path":               None,
        "cache_mode":               "streaming",
        "ext":                      None,
        "spotify_import":           True,
        "spotify_confidence":       round(confidence, 3),
        "spotify_name":             pt.spotify.name,
        "spotify_artist":           pt.spotify.primary_artist,
    }


# ---------------------------------------------------------------------------
# Discord message formatting helpers
# ---------------------------------------------------------------------------

def format_summary_message(pending: PendingImport) -> str:
    """Format the initial summary/review prompt shown after processing."""
    n_auto    = len(pending.auto_tracks)
    n_review  = len(pending.pending_tracks)
    n_none    = len(pending.no_match_tracks)
    total     = len(pending.tracks)

    lines = [
        f"🎧 **Spotify Import** — *{_esc(pending.playlist_name)}* · {total} track(s)",
        f"`id: {pending.import_id}`",
        "",
    ]
    if n_auto:
        lines.append(f"✅ **{n_auto}** auto-matched (high confidence)")
    if n_review:
        lines.append(f"⚠️  **{n_review}** need review")
    if n_none:
        lines.append(f"❌ **{n_none}** — no YouTube match found (will use search fallback)")

    if n_review == 0:
        lines += [
            "",
            f"All {n_auto} tracks matched automatically.",
            f"React {REVIEW_EMOJI_ACCEPT_ALL} to **save** the playlist.",
            f"React {REVIEW_EMOJI_SKIP_UNCERTAIN} to **cancel**.",
        ]
    else:
        uncertain_preview = []
        for pt in pending.pending_tracks[:5]:
            m = pt.best_match
            if m:
                uncertain_preview.append(
                    f"  {m.confidence_emoji} {m.confidence_pct}  "
                    f"{_esc(pt.spotify.name)} → {_esc(m.title[:40])}"
                )
            else:
                uncertain_preview.append(
                    f"  🔴  {_esc(pt.spotify.name)} — no match"
                )
        if len(pending.pending_tracks) > 5:
            uncertain_preview.append(f"  _…and {len(pending.pending_tracks) - 5} more_")

        lines += [
            "",
            "**Uncertain tracks:**",
            *uncertain_preview,
            "",
            f"React {REVIEW_EMOJI_ACCEPT_ALL} save {n_auto + n_review} tracks (accept all including uncertain)",
            f"React {REVIEW_EMOJI_SKIP_UNCERTAIN} save only {n_auto} auto-matched tracks",
            f"React {REVIEW_EMOJI_STEP_REVIEW} review uncertain tracks one by one",
        ]
    return "\n".join(lines)


def format_track_review_message(pending: PendingImport) -> str:
    """Format the per-track review message for the current review_index."""
    uncertain = pending.pending_tracks
    if pending.review_index >= len(uncertain):
        # All done
        n_acc = len(pending.accepted_tracks)
        return (
            f"🎧 **Review complete** — import `{pending.import_id}`\n\n"
            f"Accepted {n_acc} track(s) total.\n"
            f"React {REVIEW_EMOJI_ACCEPT_ALL} to **save the playlist** | "
            f"{REVIEW_EMOJI_SKIP_UNCERTAIN} to **cancel**."
        )

    pt = uncertain[pending.review_index]
    m = pt.active_match
    idx_display = f"{pending.review_index + 1}/{len(uncertain)}"
    alt_label = f" · alt {pt.alt_index}/{len(pt.alternatives)}" if pt.alt_index > 0 else ""
    has_more_alts = bool(pt.alternatives) or pt.alt_index > 0

    lines = [
        f"🎧 **Track review** {idx_display}{alt_label} — import `{pending.import_id}`",
        "",
        f"Spotify:  {pt.spotify.display} · {pt.spotify.duration_display}",
    ]
    if m:
        lines += [
            f"YouTube:  **{_esc(m.title)}** · {_esc(m.channel)} · {m.duration_display}",
            f"Confidence: {m.confidence_emoji} **{m.confidence_pct}**",
            f"🔗 {m.short_url}",
        ]
    else:
        lines += [
            "YouTube:  _no match found — will use search fallback if accepted_",
        ]

    controls = [
        f"{REVIEW_EMOJI_ACCEPT} accept",
        f"{REVIEW_EMOJI_SKIP} skip",
    ]
    if has_more_alts:
        controls.append(f"{REVIEW_EMOJI_ALT} try next match")
    controls.append(f"{REVIEW_EMOJI_SKIP_ALL} accept all remaining")

    lines += ["", "  ·  ".join(controls)]
    return "\n".join(lines)


def _esc(text: str) -> str:
    """Escape markdown special chars for Discord output."""
    try:
        import discord
        return discord.utils.escape_markdown(str(text or ""))
    except ImportError:
        return re.sub(r"([*_`~\\|>])", r"\\\1", str(text or ""))
