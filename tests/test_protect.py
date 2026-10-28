"""Tests for the deletion safety net. No Gmail account or model server needed.

The rule of thumb: an email that holds something you might need (key, code, activation link,
receipt) must never become deletable, even when the model is fooled into calling it junk.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from keepsift import cleanup, config, mail, protect  # noqa: E402
from keepsift.store import Store  # noqa: E402

SAMPLES = ROOT / "samples"


def cfg():
    return config.validate(config.starter_config())


def sample(name):
    return mail.parse_message((SAMPLES / f"{name}.eml").read_bytes())


class Stub:
    """Just enough of an Email for content checks on a plain string."""

    def __init__(self, text):
        self.subject, self.body, self.html_text = "", text, ""
        self.links, self.attachments = [], []
        self.from_addr, self.starred, self.parse_error = "x@example.com", False, ""

    def all_text(self):
        return self.body


class SafetyNet(unittest.TestCase):
    def test_protected_samples_are_kept_by_rules_alone(self):
        for name in ("7-product-key", "8-activation-link", "9-key-in-html-only", "10-steam-gift"):
            with self.subTest(name=name):
                self.assertTrue(protect.email_blockers(cfg(), sample(name)), f"{name} would be deletable")

    def test_plain_junk_is_deletable(self):
        self.assertEqual(protect.email_blockers(cfg(), sample("6-junk-promo")), [])

    def test_phrases_that_must_be_protected(self):
        must = [
            "Your license key is below", "Serial Number: 1234", "activate your account",
            "Click to verify your email", "Your one-time passcode is 123456", "Reset your password",
            "Here is your Steam key", "Redeem your gift card", "Your 2FA backup codes",
            "Your recovery phrase", "Confirm your email address", "Activation code: 99",
            "XBOX code inside", "Download link for your purchase", "Your order confirmation #5521",
            "Receipt for your payment", "Your boarding pass", "Magic link to sign in",
            "new sign-in to your account", "API key created", "Enter code ABCD1-EFGH2-IJKL3",
            "Your PIN code", "warranty registration", "Your e-ticket",
            "steam wallet code: 4HQ2T 8MZ9X 3KP7L", "Google Play gift card inside",
            "Here: 7XK2P 9QWER M4N8T", "Your Office 2024 license", "V-Bucks code for you",
            "Amazon credit: $25", "use this code = HELLO", "Your Adobe serial", "GKZ84-TT2QW-PLM3R",
        ]
        missed = [p for p in must if not protect.content_hits(cfg(), Stub(p))]
        self.assertEqual(missed, [])

    def test_ordinary_marketing_is_not_protected(self):
        junk = ["40% off everything this weekend", "We miss you! Come back", "Your weekly newsletter",
                "FREE SHIPPING ON ORDERS 2026", "Use code FALL20 for 20% off", "John liked your post"]
        flagged = [j for j in junk if protect.content_hits(cfg(), Stub(j))]
        self.assertEqual(flagged, [])

    def test_unreadable_email_is_never_deletable(self):
        em = mail.unreadable_email(b"From: a@b.com\r\n\r\nhi", "1", "2", "3", False, ValueError("x"))
        self.assertIn("couldn't read", " ".join(protect.email_blockers(cfg(), em)))


class Parsing(unittest.TestCase):
    def test_broken_charsets_do_not_crash(self):
        for charset in ('"charset=us-ascii"', "x-made-up", "charset=charset=utf-8"):
            raw = (f"From: a@b.com\r\nSubject: hi\r\nContent-Type: text/plain; charset={charset}\r\n\r\n"
                   "hello there\r\n").encode()
            with self.subTest(charset=charset):
                self.assertIn("hello", mail.parse_message(raw).body)

    def test_hidden_html_link_targets_are_seen(self):
        self.assertTrue(any("activate" in link for link in sample("8-activation-link").links))


def html_email(sender, subject, html):
    return (f"From: {sender}\r\nTo: you@gmail.com\r\nSubject: {subject}\r\nDate: Tue, 27 Oct 2026 10:00:00 +0000\r\n"
            f"MIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<html><body>{html}</body></html>").encode()


FOOTER = ('<p>Forgot your password? <a href="https://social.example/account/begin_password_reset?account=someone">'
          'reset it</a>.</p><p>Reset password</p>')


class FakeGmail:
    def __init__(self, inbox):
        self.inbox, self.fate = inbox, {}

    def fetch(self, uids, max_bytes):
        return [mail.parse_message(self.inbox[u], u, "m" + u) for u in uids]

    def trash(self, uid):
        self.fate[uid] = "trashed"

    def add_label(self, uid, label):
        self.fate.setdefault(uid, label)

    def remove_label(self, uid, label):
        pass


class Cleanup(unittest.TestCase):
    def run_cleanup(self, emails):
        """emails: list of (tag, raw). Returns {tag: set of fates}."""
        inbox = {str(i): raw for i, (_, raw) in enumerate(emails)}
        items = []
        for uid, raw in inbox.items():
            em = mail.parse_message(raw, uid, "m" + uid)
            items.append({"uid": uid, "gm_msgid": "m" + uid, "from_addr": em.from_addr, "from_name": "",
                          "subject": em.subject, "date": "2026-10-27", "size": len(raw), "starred": False})
        gmail = FakeGmail(inbox)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "t.db")
            cleanup.clean(cfg(), None, store, gmail, items, "trash", False, report=lambda *_: None)
            store.db.close()
        fates = {}
        for (tag, _), uid in zip(emails, inbox):
            fates.setdefault(tag, set()).add(gmail.fate.get(uid, "untouched"))
        return fates

    def test_repeated_footer_does_not_block_cleanup_but_real_mail_is_kept(self):
        emails = [("notification", html_email("Social <info@social.example>", f"{i} new updates",
                                              f"<p>Update number {i}.</p>" + FOOTER)) for i in range(8)]
        emails.append(("real-reset", html_email("Social <info@social.example>", "Password reset request",
                       '<a href="https://social.example/reset?token=9f8e7d6c5b">Reset password</a>' + FOOTER)))
        emails += [("same-key", html_email("Licensing <lic@tool.example>", f"Update {i}",
                    "<p>Your license key: TQ4X2-88KJW-ZP3M7-QQ9VR</p>")) for i in range(6)]
        fates = self.run_cleanup(emails)
        self.assertEqual(fates["notification"], {"trashed"})
        self.assertNotIn("trashed", fates["real-reset"])
        self.assertNotIn("trashed", fates["same-key"])

    def test_duplicate_activation_emails_are_all_kept(self):
        raw = (SAMPLES / "8-activation-link.eml").read_bytes()
        fates = self.run_cleanup([("activation", raw)] * 8)
        self.assertNotIn("trashed", fates["activation"])

    def test_duplicate_receipts_with_order_numbers_are_kept(self):
        raw = html_email("Shop <news@shop.example>", "Your purchase",
                         "<p>Thanks! Your order number is 112-5566-9910.</p>")
        fates = self.run_cleanup([("receipt", raw)] * 6)
        self.assertNotIn("trashed", fates["receipt"])


if __name__ == "__main__":
    unittest.main()
