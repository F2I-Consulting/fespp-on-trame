"""Text as the command engine reads it: lower case, no accents, the French
decimal comma made a point, punctuation made space — "Montre la porosité
au-dessus de 0,2 !" and "montre la porosite au dessus de 0.2" are one text.

Numbers are read the way people type them: "2 500" (a thousands space) is
2500, "≤" is "<=", "k=10" says k = 10, and "≠" or "!=" is the word "neq" (a
value said NOT, never an equal sign). A hyphen between two numbers stays in
its token: "0,1-0,3" may be a range and "9-19" the end of a well's name
("15/9-19 A") — slots.py decides, knowing the session's titles."""
import re
import unicodedata

_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
_KEEP = re.compile(r"[^a-z0-9.%<>=/+\- ]+")
_SPACES = re.compile(r"\s+")
# "2 500", "1 000 000" (a space, a no-break space or a thin one between
# groups of three digits); a decimal before it ("0.5 100") is two numbers
_THOUSANDS = re.compile(r"(?<![\d.,])([1-9]\d{0,2})((?:[^\S\r\n\t]\d{3})+)\b(?![.,]\d)")


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize(text):
    # "≠" before the accents go: its decomposition is "=" and a stroke
    s = str(text or "").replace("≠", " neq ").replace("!=", " neq ")
    s = strip_accents(s.lower())
    s = s.replace("’", "'").replace("'", " ").replace("≤", "<=").replace("≥", ">=")
    s = _THOUSANDS.sub(lambda m: m.group(1) + re.sub(r"\D", "", m.group(2)), s)
    s = _DECIMAL_COMMA.sub(".", s)
    s = _KEEP.sub(" ", s)
    # "poro >0.18": the comparison is a word of its own
    s = re.sub(r"([<>]=?)", r" \1 ", s)
    # "k=10": the equal sign too (not the one of "<=")
    s = re.sub(r"(?<![<>=])=+", " = ", s)
    # a hyphen between letters is a word joint ("au-dessus", "net-to-gross"),
    # between a letter and a digit a name ("F-4") — kept only there
    s = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", s)
    # a point that ends a sentence is not a decimal point
    s = re.sub(r"\.(?!\d)", " ", s)
    return _SPACES.sub(" ", s).strip()


def tokens(text):
    return normalize(text).split()
