import re
import random
from pathlib import Path

QUOTES_FILE = Path("quotes.txt")


def _ensure_quotes_file():
    """Guarantee that quotes.txt exists so incremental writes do not fail."""
    if not QUOTES_FILE.exists():
        QUOTES_FILE.touch()


def saveQuotes(quotes):
    _ensure_quotes_file()
    with QUOTES_FILE.open("w", errors="surrogateescape") as file:
        author = None

        for quote in quotes:
            if not quote:
                continue

            first_char_ascii = ord(quote[0])
            if first_char_ascii == 45 or first_char_ascii == 8226:  # Quote starts with "-" or "•"
                author = quote

            else:
                if author is None:
                    line_to_save = re.sub(r'(\n)+', " ", f"{quote}")

                else:
                    line_to_save = re.sub(r'(\n)+', " ", f"{quote} {author}")

                try:
                    file.write(f"{line_to_save}\n")
                except UnicodeEncodeError:
                    pass

                author = None


def saveSingleQuote(quote):
    _ensure_quotes_file()
    if not quote:
        return
    with QUOTES_FILE.open("r+", errors="surrogateescape") as file:
        saved_quotes = file.readlines()

        first_char_ascii = ord(quote[0])
        if first_char_ascii == 45 or first_char_ascii == 8226:  # Quote starts with "-" or "•"
            leading = saved_quotes.pop(0) if saved_quotes else ""
            quote_to_save = re.sub(r'(\n)+', " ", f"{leading} {quote}")

        else:
            quote_to_save = re.sub(r'(\n)+', " ", f"{quote}")

        saved_quotes.insert(0, f"{quote_to_save}\n")
        try:
            file.seek(0)
            file.writelines(saved_quotes)
        except UnicodeEncodeError:
            pass


def getRandomQuote():
    _ensure_quotes_file()
    lines = QUOTES_FILE.read_text(errors="surrogateescape").splitlines()
    if not lines:
        return "No quotes saved yet."
    return random.choice(lines)
