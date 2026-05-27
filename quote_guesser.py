"""
Daily quote guesser module.

Each day all users see the same randomly-selected attributed quote from quotes.txt.
They get 3 tries: 9 pts on the first, 6 on the second, 3 on the third, 0 if all wrong.
Four multiple-choice options are shown (the correct author + 3 distractors).

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
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("quote_guesser")

POINTS_FOR_TRY = [9, 6, 3]   # indexed by (try_num - 1); 0 if all fail
MAX_TRIES = 3
CHOICES_COUNT = 4


def check_dependencies() -> list:
    """No extra packages needed."""
    return []


# ---------------------------------------------------------------------------
# Quote parsing
# ---------------------------------------------------------------------------

def parse_quote_author(line: str) -> tuple[str, Optional[str]]:
    """
    Extract (text, author) from a quotes.txt line.

    The file format produced by quotes.py appends the attribution marker
    inline, e.g.  "Great quote - Author Name"  or  "Great quote • Author".
    We look for the last occurrence of " - " or " • " to find the split.
    """
    for sep in (" • ", " - "):
        idx = line.rfind(sep)
        if idx > 0:
            text = line[:idx].strip()
            author = line[idx + len(sep):].strip()
            if text and author:
                return text, author
    return line.strip(), None


def load_attributed_quotes(quotes_path: str) -> list[dict]:
    """Load all attributed quotes from quotes.txt. Returns dicts {text, author}."""
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
    """
    Return the quote for *date_str* (YYYY-MM-DD).
    Selection is deterministic: same date → same quote for every user.
    """
    attributed = [q for q in quotes if q.get("author")]
    if not attributed:
        logger.warning("[guesser] no attributed quotes available for daily challenge")
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
    """
    Build a shuffled multiple-choice list containing *correct_author*.
    The seed (the date string) makes it identical for all users.
    """
    others = [a for a in all_authors if a != correct_author]
    rng = random.Random(seed)
    rng.shuffle(others)
    choices = [correct_author] + others[: count - 1]
    rng.shuffle(choices)
    logger.debug(f"[guesser] choices for {seed}: {choices} (correct={correct_author})")
    return choices


# ---------------------------------------------------------------------------
# Persistent state
# ---------------------------------------------------------------------------

class QuoteGuesser:
    """Manages daily challenge state and leaderboard for all players."""

    def __init__(self, base_dir: str, quotes_path: Optional[str] = None):
        self._base_dir = base_dir
        self._quotes_path = quotes_path or os.path.join(base_dir, "quotes.txt")
        self._data_path = os.path.join(base_dir, "quote_guesser_data.json")
        self._data = self._load_data()
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
                logger.debug(f"[guesser] loaded data from {self._data_path}")
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
            logger.debug(f"[guesser] data saved to {self._data_path}")
        except Exception as exc:
            logger.error(f"[guesser] save failed: {exc}")
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ── Public API ─────────────────────────────────────────────────────────

    def get_today_challenge(self, user_id: int) -> Optional[dict]:
        """
        Return today's challenge state for *user_id*.

        Returns a dict:
            text         – the quote body (no author)
            choices      – 4 author names (shuffled, same order for all users)
            date         – today's date string
            state        – {tries_used, solved, done, points_earned, wrong_guesses}
        Returns None if no attributed quotes exist.
        """
        date_str = get_today_utc()
        quotes = load_attributed_quotes(self._quotes_path)
        daily = get_daily_quote(quotes, date_str)
        if daily is None:
            logger.debug(f"[guesser] get_today_challenge: no daily quote for {date_str}")
            return None

        all_authors = get_all_authors(quotes)
        choices = make_choices(daily["author"], all_authors, seed=date_str)
        state = self._user_day_state(user_id, date_str)

        logger.debug(
            f"[guesser] today challenge for user={user_id} date={date_str} "
            f"tries_used={state['tries_used']} done={state['done']}"
        )
        return {
            "text":           daily["text"],
            "choices":        choices,
            "date":           date_str,
            "correct_author": daily["author"] if state["done"] else None,
            "state":          state,
        }

    def submit_guess(self, user_id: int, username: str, guess: str) -> dict:
        """
        Submit a guess for today's challenge.

        Returns:
            correct        – bool
            try_num        – 1-based attempt number
            tries_used     – attempts consumed so far
            points_earned  – int (only set when done=True)
            done           – whether the game is over for this user today
            correct_author – revealed when done=True
        """
        date_str = get_today_utc()
        quotes = load_attributed_quotes(self._quotes_path)
        daily = get_daily_quote(quotes, date_str)
        if daily is None:
            logger.warning("[guesser] submit_guess: no daily quote available")
            return {"error": "No daily quote available"}

        correct_author = daily["author"]
        key = f"{date_str}:{user_id}"
        history = self._data.setdefault("history", {})
        state = history.get(key) or {"tries": [], "solved": False, "points_earned": None}

        if state.get("solved") or len(state["tries"]) >= MAX_TRIES:
            logger.debug(f"[guesser] user={user_id} already finished today")
            return {"error": "Already completed today's challenge"}

        try_num = len(state["tries"]) + 1
        is_correct = guess.strip().lower() == correct_author.strip().lower()

        state["tries"].append({"guess": guess, "correct": is_correct, "try_num": try_num})
        logger.info(
            f"[guesser] user={user_id} ({username}) try={try_num}/{MAX_TRIES} "
            f"guess='{guess}' correct={is_correct}"
        )

        if is_correct:
            points = POINTS_FOR_TRY[try_num - 1]
            state.update({"solved": True, "points_earned": points,
                          "username": username, "solved_at": time.time()})
            self._add_score(user_id, username, points, solved=True)
            history[key] = state
            self._save_data()
            logger.info(f"[guesser] user={user_id} solved on try {try_num} → +{points} pts")
            return {
                "correct": True, "try_num": try_num,
                "tries_used": try_num, "points_earned": points,
                "done": True, "correct_author": correct_author,
            }

        done = len(state["tries"]) >= MAX_TRIES
        if done:
            state.update({"points_earned": 0, "username": username, "solved_at": time.time()})
            self._add_score(user_id, username, 0, solved=False)
            logger.info(f"[guesser] user={user_id} exhausted all tries → 0 pts")

        history[key] = state
        self._save_data()
        return {
            "correct": False, "try_num": try_num,
            "tries_used": len(state["tries"]),
            "points_earned": 0 if done else None,
            "done": done,
            "correct_author": correct_author if done else None,
        }

    def get_leaderboard(self, limit: int = 15) -> list[dict]:
        """Return top players sorted by cumulative score."""
        scores = self._data.get("scores", {})
        board = [
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
        key = f"{date_str}:{user_id}"
        raw = self._data.get("history", {}).get(key) or {}
        tries = raw.get("tries", [])
        wrong = [t["guess"] for t in tries if not t.get("correct")]
        solved = raw.get("solved", False)
        done = solved or len(tries) >= MAX_TRIES
        return {
            "tries_used":    len(tries),
            "solved":        solved,
            "done":          done,
            "points_earned": raw.get("points_earned"),
            "wrong_guesses": wrong,
        }

    def _add_score(self, user_id: int, username: str, points: int, *, solved: bool):
        scores = self._data.setdefault("scores", {})
        uid_key = str(user_id)
        if uid_key not in scores:
            scores[uid_key] = {"username": username, "total": 0, "games": 0, "solved": 0}
        scores[uid_key]["total"] += points
        scores[uid_key]["games"] += 1
        if solved:
            scores[uid_key]["solved"] += 1
        scores[uid_key]["username"] = username
        logger.debug(
            f"[guesser] score updated uid={user_id} total={scores[uid_key]['total']} "
            f"games={scores[uid_key]['games']} solved={scores[uid_key]['solved']}"
        )
