import os
import re
import random


def saveQuotes(quotes):
    with open("quotes.txt", "w", errors="surrogateescape") as file:
        author = None

        for quote in quotes:

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
    with open("quotes.txt", "r+", errors="surrogateescape") as file:
        saved_quotes = file.readlines()

        first_char_ascii = ord(quote[0])
        if first_char_ascii == 45 or first_char_ascii == 8226:  # Quote starts with "-" or "•"
            quote_to_save = re.sub(r'(\n)+', " ", f"{saved_quotes.pop(0)} {quote}")

        else:
            quote_to_save = re.sub(r'(\n)+', " ", f"{quote}")

        saved_quotes.insert(0, f"{quote_to_save}\n")
        try:
            file.seek(0)
            file.writelines(saved_quotes)
        except UnicodeEncodeError:
            pass


def getRandomQuote():
    lines = open("quotes.txt", "r", errors="surrogateescape").read().splitlines()
    quote = random.choice(lines)
    return quote
