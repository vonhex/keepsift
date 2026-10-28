"""Deletion safety net. Deterministic checks that run no matter what the model says.

An email is only ever marked for deletion or trashed when deletion_blockers() returns
nothing. KEYS, ACCOUNT and LINK patterns are always on and cannot be disabled from config.
"""
import re
from fnmatch import fnmatch

from . import config

# Product keys, licences, activation, codes with monetary value.
KEYS = [
    r"product\s*keys?", r"licen[cs]e\s*(key|code|number|file|id)", r"\bserials?\b",
    r"activation\s*(key|code|link|id|e-?mail|number)",
    r"activate\s+(your|the|this|my|now|account|licen[cs]e|product|subscription|key|software|device)",
    r"\b(cd|game|steam|epic|origin|uplay|ubisoft|xbox|playstation|psn|nintendo|eshop|digital|beta)\s*(key|code)s?\b",
    r"\bredeem", r"redemption\s*code", r"gift\s*cards?", r"registration\s*(key|code|number)",
    r"unlock\s*code", r"enrol+ment\s*(key|code)", r"download\s*(link|key|code)", r"your\s*(key|code)\s*(is|:)",
    r"\b(key|code)\s*[:=]\s*\S", r"\bvoucher\s*code", r"\bwallet\s*(code|card|credit)",
    # a store/brand name with key/code/card/credit shortly after: "Steam wallet code", "Google Play gift card"
    r"\b(steam|xbox|psn|playstation|nintendo|google\s*play|itunes|app\s*store|apple|amazon|roblox|v-?bucks|"
    r"riot|battle\.?net|blizzard|ea\s*play|gog|humble|microsoft|windows|office|adobe|autodesk)\b"
    r"[^.\n]{0,30}?\b(keys?|codes?|cards?|credit|licen[cs]e)\b",
]
# Account access and security.
ACCOUNT = [
    r"verif(y|ication)\s*(code|link|your|e-?mail|account|identity|number)",
    r"confirm\s*(your\s*)?(e-?mail|account|address|registration|sign[-\s]?up|identity)",
    r"one[-\s]?time\s*(code|password|passcode|pin|link)", r"\b(otp|2fa|mfa)\b", r"two[-\s]?(factor|step)",
    r"security\s*code", r"recovery\s*(code|key|phrase|e-?mail)", r"backup\s*codes?", r"seed\s*phrase",
    r"(reset|change)\s*(your\s*)?password", r"password\s*reset", r"temporary\s*password",
    r"(magic|sign[-\s]?in|log[-\s]?in|login)\s*link", r"\b(api|access|secret)\s*(key|token)",
    r"\bpasscode\b", r"\bpin\s*(code|number)\b", r"new\s*(device|sign[-\s]?in|login)",
]
# Words in a link address that suggest it does something you may need again.
LINK = re.compile(
    r"activat|verif|confirm|redeem|licen[cs]|claim|unlock|reset|passwordless|magic|sign-?in|login|"
    r"one-?time|download|onboard|setup|invite|invitation|accept", re.I)
LINK_IGNORE = re.compile(r"unsubscribe|opt-?out|preferences|manage.?subscription|email-?settings", re.I)
# Proof of purchase and documents (on by default, can be turned off).
PURCHASES = [
    r"\breceipt", r"\binvoice", r"order\s*(number|no\b|#|confirm|confirmation|details|id|summary)",
    r"purchase\s*(confirm|confirmation|receipt|details)", r"thank(s| you) for (your )?(purchase|order)",
    r"warranty", r"e-?ticket", r"boarding\s*pass", r"itinerary", r"booking\s*(confirmation|reference|number)",
    r"reservation\s*(number|confirmation|code)", r"\btax\s*(form|return|document|statement)",
    r"\b(1099|w-?2)\b", r"\brefund", r"\bcontract\b", r"subscription\s*(confirm|confirmation|receipt)",
]
# Something shaped like a key: 3+ blocks of capitals/digits split by dashes or spaces,
# e.g. ABCDE-12345-FGHIJ or 4HQ2T 8MZ9X 3KP7L. See _key_shape() for the mixed-block requirement.
KEY_SHAPE = re.compile(r"\b[A-Z0-9]{4,8}(?:[- ][A-Z0-9]{4,8}){2,}\b")

_KEYS = [re.compile(p, re.I) for p in KEYS]
_ACCOUNT = [re.compile(p, re.I) for p in ACCOUNT]
_PURCHASES = [re.compile(p, re.I) for p in PURCHASES]
URL = re.compile(r"https?://[^\s<>\"')]+", re.I)


def _first(patterns, text):
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(0).strip()
    return None


def _key_shape(text):
    """A key-like run with at least two blocks mixing letters and digits (so 'FREE SHIPPING 2026' isn't one)."""
    for m in KEY_SHAPE.finditer(text):
        blocks = re.split(r"[- ]", m.group(0))
        mixed = [b for b in blocks if re.search(r"\d", b) and re.search(r"[A-Z]", b)]
        if len(mixed) >= 2:
            return m.group(0)
    return None


# A "code: X" / "key: X" value is never treated as boilerplate, even if it repeats.
CODE_VALUE = _KEYS[KEYS.index(r"\b(key|code)\s*[:=]\s*\S")]


# Specific values that make a line or link "about something" rather than template text:
# order/reference numbers, and token-like link segments (activation and reset tokens).
SPECIFIC_NUMBER = re.compile(r"\d{5,}|\b\d{2,}[-–]\d{3,}")
TOKEN = re.compile(r"[A-Za-z0-9_\-]{8,}")


def _has_token(url):
    return any(re.search(r"\d", t) and re.search(r"[A-Za-z]", t) for t in TOKEN.findall(url.split("://", 1)[-1]))


def _line_key(text, start, end):
    """The whole line around a match, normalised. Footers repeat it exactly; real content varies."""
    a = text.rfind("\n", 0, start) + 1
    b = text.find("\n", end)
    return re.sub(r"\s+", " ", text[a:b if b != -1 else len(text)]).strip().lower()[:200]


def findings(cfg, em):
    """Everything protective found in the email, as (group, label, key, can_be_boilerplate).

    `key` identifies the exact line or link, so callers can recognise text that repeats identically
    in every email from a sender (footers) and ignore it. Keys, codes and your own protected words
    are never marked as possible boilerplate.
    """
    d = cfg["deletion"]
    text = em.all_text()
    out = []

    def phrases(group, patterns, label, can_ignore=True):
        for p in patterns:
            for m in list(p.finditer(text))[:20]:
                line = _line_key(text, m.start(), m.end())
                fixed = not can_ignore or p is CODE_VALUE or SPECIFIC_NUMBER.search(line)
                out.append((group, label.format(m.group(0).strip()), line, not fixed))

    phrases("keys", _KEYS, 'contains a key or code ("{}")')
    if m := _key_shape(text):
        out.append(("shape", f'contains something shaped like a product key ("{m}")', m, False))
    phrases("account", _ACCOUNT, 'account or security content ("{}")')
    for url in dict.fromkeys([*em.links, *URL.findall(em.body), *URL.findall(em.html_text)]):
        if not LINK_IGNORE.search(url) and (m := LINK.search(url)):
            out.append(("link", f'has a link containing "{m.group(0).lower()}" ({url[:80]})', url,
                        not _has_token(url)))  # a link with its own token is never a footer
    if d["protect_purchases"]:
        phrases("purchase", _PURCHASES, 'proof of purchase or document ("{}")')
    low = text.lower()
    for word in d["extra_protect_keywords"]:
        if word.strip() and word.strip().lower() in low:
            out.append(("yours", f'contains your protected word "{word.strip()}"', word, False))
    return out


def content_hits(cfg, em, boilerplate=frozenset()):
    """Reasons found in the email's own content (one per kind). Empty means nothing protected was found.

    boilerplate: keys of lines/links known to repeat in every email from this sender; they're ignored.
    """
    reasons, seen = [], set()
    for group, label, key, can_ignore in findings(cfg, em):
        if can_ignore and key in boilerplate:
            continue
        if group not in seen:
            seen.add(group)
            reasons.append(label)
    return reasons


def learn_boilerplate(cfg, emails, min_count=4, share=0.5):
    """Lines/links that appear identically in at least half (and at least 4) of these emails.

    Use on emails from ONE sender. Footers ("Forgot your password? Reset it here") repeat word for
    word; a real reset link or receipt line has its own token, number or wording each time.
    """
    from collections import Counter
    counts = Counter()
    for em in emails:
        counts.update({key for _, _, key, can_ignore in findings(cfg, em) if can_ignore})
    need = max(min_count, share * len(emails))
    return {key for key, n in counts.items() if n >= need}


def wants_delete(cfg, cls):
    return (cfg["deletion"]["enabled"] and not cls.get("ignore")
            and config.category(cfg, cls["category"])["delete"])


def email_blockers(cfg, em, boilerplate=frozenset()):
    """Reasons to keep that depend only on the email itself (no model). Used by triage and cleanup."""
    d, tri = cfg["deletion"], cfg["triage"]
    reasons = []
    if em.parse_error:
        reasons.append("couldn't read the email properly, so it can't be checked")
    reasons += content_hits(cfg, em, boilerplate)
    if d["protect_attachments"] and em.attachments:
        reasons.append("has attachments")
    if d["protect_starred"] and em.starred:
        reasons.append("is starred")
    if any(fnmatch(em.from_addr, p.lower()) for p in d["protect_senders"]):
        reasons.append("sender is on your never-delete list")
    if any(fnmatch(em.from_addr, p.lower()) for p in tri["vip_senders"]):
        reasons.append("sender is a VIP")
    return reasons


def deletion_blockers(cfg, em, cls):
    """Every reason this email must NOT be deleted. Empty list means it may be."""
    d = cfg["deletion"]
    reasons = []
    if not wants_delete(cfg, cls):
        reasons.append("category is not set to delete")
    if "has_lasting_value" not in cls:
        reasons.append("the model's keep-check did not run")
    elif cls["has_lasting_value"]:
        reasons.append(f"model says keep it: {cls.get('keep_reason') or 'has lasting value'}")
    reasons += email_blockers(cfg, em)
    if cls["needs_reply"]:
        reasons.append("needs a reply")
    if cls["priority"] == "urgent":
        reasons.append("is urgent")
    if cls["suspicious"]:
        reasons.append("is suspicious (kept so you see the warning)")
    if cls["confidence"] < d["min_confidence"]:
        reasons.append(f"confidence {cls['confidence']:.2f} is below {d['min_confidence']}")
    return reasons
