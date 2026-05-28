"""
Daily quote guesser module.

Each day all users see the same randomly-selected attributed quote from quotes.txt.
They get 3 tries: 9 pts on the first, 6 on the second, 3 on the third, 0 if all wrong.
Four multiple-choice options are shown (the correct author + 3 distractors).

Admins can also play an unlimited mode (random quotes, no leaderboard effect) via the
WebUI ∞ button. Unlimited sessions are in-memory only and do not affect scores.

Enabled when QUOTE_GUESSER_ENABLED=true and WEBUI_ENABLED=true.
Requires at least one attributed quote in quotes.txt (lines ending with " - Author").

Persistence:
    BASE_DIR/quote_guesser_data.json
        .scores   – cumulative leaderboard
        .history  – per-user per-day attempt records
"""

import hashlib
import json
import logging
import os
import random
import re
import secrets
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("quote_guesser")

POINTS_FOR_TRY = [9, 6, 3]
MAX_TRIES      = 3
CHOICES_COUNT  = 4

# ---------------------------------------------------------------------------
# Quote parsing
# ---------------------------------------------------------------------------

def check_dependencies() -> list:
    return []


def parse_quote_author(line: str) -> tuple[str, Optional[str]]:
    for sep in (" • ", " - "):
        idx = line.rfind(sep)
        if idx > 0:
            text   = line[:idx].strip()
            author = line[idx + len(sep):].strip()
            if text and author:
                return text, author
    return line.strip(), None


def load_attributed_quotes(quotes_path: str) -> list[dict]:
    if not os.path.isfile(quotes_path):
        logger.debug(f"[guesser] quotes file not found: {quotes_path}")
        return []
    try:
        lines = open(quotes_path, errors="surrogateescape").read().splitlines()
    except Exception as exc:
        logger.error(f"[guesser] failed to read quotes file: {exc}")
        return []
    result = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        text, author = parse_quote_author(line)
        if author:
            result.append({"text": text, "author": author})
    logger.debug(f"[guesser] loaded {len(result)} attributed quotes from {len(lines)} lines")
    return result

# ---------------------------------------------------------------------------
# Daily quote selection
# ---------------------------------------------------------------------------

def get_today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_daily_quote(quotes: list[dict], date_str: str) -> Optional[dict]:
    attributed = [q for q in quotes if q.get("author")]
    if not attributed:
        return None
    idx = int(hashlib.md5(date_str.encode()).hexdigest(), 16) % len(attributed)
    return attributed[idx]


def get_all_authors(quotes: list[dict]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in quotes:
        a = (q.get("author") or "").strip()
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    return out


def make_choices(correct_author: str, all_authors: list[str],
                 seed: str, count: int = CHOICES_COUNT) -> list[str]:
    others = [a for a in all_authors if a != correct_author]
    rng = random.Random(seed)
    rng.shuffle(others)
    choices = [correct_author] + others[:count - 1]
    rng.shuffle(choices)
    return choices

# ---------------------------------------------------------------------------
# QuoteGuesser
# ---------------------------------------------------------------------------

class QuoteGuesser:
    """Manages daily challenge state, leaderboard, and unlimited admin mode."""

    def __init__(self, base_dir: str, quotes_path: Optional[str] = None):
        self._base_dir    = base_dir
        self._quotes_path = quotes_path or os.path.join(base_dir, "quotes.txt")
        self._data_path   = os.path.join(base_dir, "quote_guesser_data.json")
        self._data        = self._load_data()
        # In-memory unlimited sessions: session_id → {quote, choices, tries, done}
        self._unlimited: dict[str, dict] = {}
        logger.info(
            f"[guesser] initialised | quotes={self._quotes_path} "
            f"data={self._data_path} | "
            f"players={len(self._data.get('scores', {}))} "
            f"history_entries={len(self._data.get('history', {}))}"
        )

    # ── Persistence ────────────────────────────────────────────────────────

    def _load_data(self) -> dict:
        if os.path.isfile(self._data_path):
            try:
                with open(self._data_path) as f:
                    data = json.load(f)
                return data
            except Exception as exc:
                logger.error(f"[guesser] failed to load data, starting fresh: {exc}")
        return {"scores": {}, "history": {}}

    def _save_data(self):
        fd, tmp = tempfile.mkstemp(prefix=".tmp-qg-", suffix=".json", dir=self._base_dir)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f, indent=2)
                f.write("\n")
            os.replace(tmp, self._data_path)
        except Exception as exc:
            logger.error(f"[guesser] save failed: {exc}")
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ── Daily challenge ─────────────────────────────────────────────────────

    def get_today_challenge(self, user_id: int) -> Optional[dict]:
        date_str    = get_today_utc()
        quotes      = load_attributed_quotes(self._quotes_path)
        daily       = get_daily_quote(quotes, date_str)
        if daily is None:
            return None

        all_authors = get_all_authors(quotes)
        choices     = make_choices(daily["author"], all_authors, seed=date_str)
        state       = self._user_day_state(user_id, date_str)

        return {
            "text":           daily["text"],
            "choices":        choices,
            "date":           date_str,
            "correct_author": daily["author"] if state["done"] else None,
            "state":          state,
        }

    def submit_guess(self, user_id: int, username: str, guess: str) -> dict:
        date_str = get_today_utc()
        quotes   = load_attributed_quotes(self._quotes_path)
        daily    = get_daily_quote(quotes, date_str)
        if daily is None:
            return {"error": "No daily quote available"}

        correct_author = daily["author"]
        key     = f"{date_str}:{user_id}"
        history = self._data.setdefault("history", {})
        state   = history.get(key) or {"tries": [], "solved": False, "points_earned": None}

        if state.get("solved") or len(state["tries"]) >= MAX_TRIES:
            return {"error": "Already completed today's challenge"}

        try_num    = len(state["tries"]) + 1
        is_correct = guess.strip().lower() == correct_author.strip().lower()
        state["tries"].append({"guess": guess, "correct": is_correct, "try_num": try_num})

        if is_correct:
            points = POINTS_FOR_TRY[try_num - 1]
            state.update({"solved": True, "points_earned": points,
                          "username": username, "solved_at": time.time()})
            self._add_score(user_id, username, points, solved=True)
            history[key] = state
            self._save_data()
            return {
                "correct": True, "try_num": try_num,
                "tries_used": try_num, "points_earned": points,
                "done": True, "correct_author": correct_author,
            }

        done = len(state["tries"]) >= MAX_TRIES
        if done:
            state.update({"points_earned": 0, "username": username,
                          "solved_at": time.time()})
            self._add_score(user_id, username, 0, solved=False)

        history[key] = state
        self._save_data()
        return {
            "correct": False, "try_num": try_num,
            "tries_used": len(state["tries"]),
            "points_earned": 0 if done else None,
            "done": done,
            "correct_author": correct_author if done else None,
        }

    # ── Unlimited mode (admin only, no leaderboard) ─────────────────────────

    def get_unlimited_challenge(self, user_id: int) -> Optional[dict]:
        """
        Start a new unlimited-mode round for *user_id*.
        Picks a random attributed quote, creates an in-memory session.
        Returns the session dict, or None if no attributed quotes exist.
        """
        quotes = load_attributed_quotes(self._quotes_path)
        attributed = [q for q in quotes if q.get("author")]
        if not attributed:
            return None

        # Pick a random quote with a time-based seed so it's different each call
        seed  = secrets.token_hex(8)
        rng   = random.Random(seed)
        quote = rng.choice(attributed)

        all_authors = get_all_authors(quotes)
        choices     = make_choices(quote["author"], all_authors, seed=seed)

        session_id = secrets.token_urlsafe(12)
        self._unlimited[session_id] = {
            "session_id":     session_id,
            "user_id":        user_id,
            "text":           quote["text"],
            "correct_author": quote["author"],
            "choices":        choices,
            "tries":          [],
            "done":           False,
            "created_at":     time.time(),
        }
        logger.debug(f"[guesser] unlimited session {session_id} for user={user_id}")
        return {
            "session_id": session_id,
            "text":       quote["text"],
            "choices":    choices,
            "done":       False,
        }

    def submit_unlimited_guess(self, session_id: str, user_id: int,
                               username: str, guess: str) -> dict:
        """
        Submit a guess for an unlimited-mode session.
        No effect on leaderboard. Expires old sessions (> 2h) on access.
        """
        self._expire_unlimited_sessions()

        session = self._unlimited.get(session_id)
        if session is None:
            return {"error": "Session not found or expired — start a new round"}
        if session["done"]:
            return {"error": "Round already finished — start a new round"}

        correct_author = session["correct_author"]
        tries          = session["tries"]
        try_num        = len(tries) + 1
        is_correct     = guess.strip().lower() == correct_author.strip().lower()

        tries.append({"guess": guess, "correct": is_correct, "try_num": try_num})
        done = is_correct or try_num >= MAX_TRIES
        session["done"] = done

        return {
            "correct":        is_correct,
            "try_num":        try_num,
            "tries_used":     len(tries),
            "done":           done,
            "correct_author": correct_author if done else None,
        }

    def _expire_unlimited_sessions(self, max_age_seconds: int = 7200):
        now     = time.time()
        expired = [
            sid for sid, s in self._unlimited.items()
            if now - s["created_at"] > max_age_seconds
        ]
        for sid in expired:
            del self._unlimited[sid]

    # ── Leaderboard ─────────────────────────────────────────────────────────

    def get_leaderboard(self, limit: int = 15) -> list[dict]:
        scores = self._data.get("scores", {})
        board  = [
            {
                "user_id":  uid,
                "username": s.get("username", f"user-{uid}"),
                "total":    s.get("total", 0),
                "games":    s.get("games", 0),
                "solved":   s.get("solved", 0),
            }
            for uid, s in scores.items()
        ]
        board.sort(key=lambda x: x["total"], reverse=True)
        return board[:limit]

    # ── Internal helpers ────────────────────────────────────────────────────

    def _user_day_state(self, user_id: int, date_str: str) -> dict:
        key   = f"{date_str}:{user_id}"
        raw   = self._data.get("history", {}).get(key) or {}
        tries = raw.get("tries", [])
        wrong = [t["guess"] for t in tries if not t.get("correct")]
        solved = raw.get("solved", False)
        done   = solved or len(tries) >= MAX_TRIES
        return {
            "tries_used":    len(tries),
            "solved":        solved,
            "done":          done,
            "points_earned": raw.get("points_earned"),
            "wrong_guesses": wrong,
        }

    def _add_score(self, user_id: int, username: str, points: int, *, solved: bool):
        scores  = self._data.setdefault("scores", {})
        uid_key = str(user_id)
        if uid_key not in scores:
            scores[uid_key] = {"username": username, "total": 0, "games": 0, "solved": 0}
        scores[uid_key]["total"]   += points
        scores[uid_key]["games"]   += 1
        if solved:
            scores[uid_key]["solved"] += 1
        scores[uid_key]["username"] = username
