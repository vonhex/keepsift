"""Gmail access over IMAP/SMTP with an app password, plus MIME parsing."""
import email
import email.policy
import imaplib
import re
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

FETCH_CHUNK = 50


@dataclass
class Email:
    uid: str = ""
    gm_msgid: str = ""
    thread_id: str = ""
    message_id: str = ""
    references: str = ""
    from_name: str = ""
    from_addr: str = ""
    reply_to: str = ""
    to: str = ""
    cc: str = ""
    subject: str = ""
    date: str = ""
    body: str = ""
    is_bulk: bool = False
    starred: bool = False
    attachments: list = field(default_factory=list)
    links: list = field(default_factory=list)  # every href in the HTML part
    html_text: str = ""                         # HTML part as text, even when a plain part exists
    parse_error: str = ""                       # set when the email couldn't be parsed properly

    def all_text(self):
        """Everything a deletion safety check should search."""
        return "\n".join([self.subject, self.body, self.html_text, *self.links, *self.attachments])


# ---------- parsing ----------

class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "head", "title"}
    BLOCK = {"p", "div", "br", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.links = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "action") and value and not value.startswith(("#", "mailto:")):
                self.links.append(value)
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html):
    return html_parse(html)[0]


def html_parse(html):
    """(text, links) from an HTML document."""
    p = _HTMLText()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html), re.findall(r'href=["\']?([^"\'\s>]+)', html, re.I)
    return "".join(p.out), p.links


def clean_text(text):
    text = re.sub(r"[​-‏͏⁠﻿­]", "", text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _decode(data, charset):
    """Decode bytes, surviving junk charsets like 'charset=us-ascii' or made-up names."""
    cs = (charset or "utf-8").strip().strip("\"'").lower()
    cs = cs.rsplit("=", 1)[-1].strip("\"'") or "utf-8"
    for candidate in (cs, "utf-8"):
        try:
            return data.decode(candidate, errors="replace")
        except LookupError:
            continue
    return data.decode("latin-1")


def _part_text(part):
    try:
        return part.get_content()
    except Exception:
        try:
            payload = part.get_payload(decode=True) or b""
        except Exception:
            payload = str(part.get_payload()).encode("utf-8", errors="replace")
        if isinstance(payload, str):
            return payload
        try:
            charset = part.get_content_charset()
        except Exception:
            charset = None
        return _decode(payload, charset)


def _safe_body(msg, kind):
    try:
        return msg.get_body(preferencelist=(kind,))
    except Exception:
        return None


def parse_message(raw, uid="", gm_msgid="", thread_id="", starred=False):
    msg = email.message_from_bytes(raw, policy=email.policy.default)

    def h(name):
        try:
            return str(msg.get(name, "") or "").strip()
        except Exception:
            return ""

    from_name, from_addr = parseaddr(h("From"))
    body, html_text, links = "", "", []
    plain = _safe_body(msg, "plain")
    if plain is not None:
        body = _part_text(plain)
    html = _safe_body(msg, "html")
    if html is not None:
        html_text, links = html_parse(_part_text(html))
        html_text = clean_text(html_text)
    if not body.strip():
        body = html_text

    attachments = []
    try:
        attachments = [p.get_filename() or "unnamed" for p in msg.iter_attachments()]
    except Exception:
        pass

    is_bulk = bool(
        h("List-Unsubscribe") or h("List-Id")
        or h("Precedence").lower() in ("bulk", "list", "junk")
        or (h("Auto-Submitted") and h("Auto-Submitted").lower() != "no")
    )
    return Email(
        uid=uid, gm_msgid=gm_msgid or h("Message-ID"), thread_id=thread_id,
        message_id=h("Message-ID"), references=h("References"),
        from_name=from_name, from_addr=from_addr.lower(), reply_to=h("Reply-To"),
        to=h("To"), cc=h("Cc"), subject=h("Subject"), date=h("Date"),
        body=clean_text(body), is_bulk=is_bulk, starred=starred, attachments=attachments,
        links=links, html_text=html_text,
    )


def unreadable_email(raw, uid, gm_msgid, thread_id, starred, error):
    """Best-effort stand-in when MIME parsing fails: raw text, so the model still sees something."""
    text = raw.decode("utf-8", errors="replace")
    head, _, body = text.partition("\r\n\r\n") if "\r\n\r\n" in text else text.partition("\n\n")
    hdr = lambda name: (re.search(rf"(?im)^{name}:\s*(.+)$", head) or [None, ""])[1].strip()
    from_name, from_addr = parseaddr(hdr("From"))
    return Email(uid=uid, gm_msgid=gm_msgid, thread_id=thread_id, from_name=from_name,
                 from_addr=from_addr.lower(), subject=hdr("Subject"), date=hdr("Date"),
                 message_id=hdr("Message-ID"), body=clean_text(body)[:50000], starred=starred,
                 parse_error=f"{type(error).__name__}: {error}")


def header_info(raw, meta, size):
    """Parse a header-only fetch into a small dict; never raises."""
    vals = {}
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception:
        msg = None
    text = raw.decode("utf-8", errors="replace")
    for name in ("From", "Subject", "Date"):
        try:
            vals[name] = str(msg.get(name, "") or "").strip() if msg is not None else ""
        except Exception:
            vals[name] = ""
        if not vals[name]:
            m = re.search(rf"(?im)^{name}:\s*(.+)$", text)
            vals[name] = m.group(1).strip() if m else ""
    from_name, from_addr = parseaddr(vals["From"])
    try:
        date = parsedate_to_datetime(vals["Date"]).strftime("%Y-%m-%d")
    except Exception:
        date = ""
    return {"uid": meta.get("UID", ""), "gm_msgid": meta.get("X-GM-MSGID", ""), "from_name": from_name,
            "from_addr": from_addr.lower() or "(unknown)", "subject": vals["Subject"], "date": date,
            "size": size, "starred": meta.get("starred", False)}


def is_noreply(addr):
    return bool(re.search(r"no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce", addr, re.I))


def reply_target(em):
    """Address a reply goes to: Reply-To if present, else the sender."""
    if em.reply_to:
        addrs = [a for _, a in getaddresses([em.reply_to]) if a]
        if addrs:
            return addrs[0].lower()
    return em.from_addr


def recipients(em):
    """Every address on To and Cc, lowercased."""
    return [a.lower() for _, a in getaddresses([em.to, em.cc]) if a]


def reply_cc(em, my_addr):
    """Reply-all Cc list: original To/Cc minus me and the primary reply target."""
    skip = {my_addr.lower(), reply_target(em)}
    seen, out = set(), []
    for name, addr in getaddresses([em.to, em.cc]):
        a = addr.lower()
        if a and a not in skip and a not in seen:
            seen.add(a)
            out.append(formataddr((name, addr)) if name else addr)
    return out


def build_reply(em, my_addr, my_name, body, quote_original=True, quote_max_lines=80, reply_all=False):
    m = EmailMessage()
    m["From"] = formataddr((my_name, my_addr)) if my_name else my_addr
    m["To"] = em.reply_to or (formataddr((em.from_name, em.from_addr)) if em.from_name else em.from_addr)
    subject = em.subject or ""
    m["Subject"] = subject if re.match(r"(?i)re:", subject) else f"Re: {subject}"
    if reply_all:
        cc = reply_cc(em, my_addr)
        if cc:
            m["Cc"] = ", ".join(cc)
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=my_addr.split("@")[-1] or None)
    if em.message_id:
        m["In-Reply-To"] = em.message_id
        m["References"] = f"{em.references} {em.message_id}".strip()
    text = body.rstrip() + "\n"
    if quote_original and em.body:
        who = em.from_name or em.from_addr
        quoted = "\n".join("> " + line for line in em.body.splitlines()[:quote_max_lines])
        text += f"\nOn {em.date}, {who} wrote:\n{quoted}\n"
    m.set_content(text)
    return m


# ---------- IMAP ----------

def _quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _meta(head):
    out = {}
    for key in ("UID", "X-GM-MSGID", "X-GM-THRID"):
        m = re.search(rb"(?<![\w-])" + key.encode() + rb" (\d+)", head)
        if m:
            out[key] = m.group(1).decode()
    m = re.search(rb"FLAGS \(([^)]*)\)", head)
    out["starred"] = bool(m and b"\\Flagged" in m.group(1))
    return out


class Gmail:
    def __init__(self, address, password, host="imap.gmail.com", port=993):
        if not address or not password:
            raise SystemExit("Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env (see README).")
        self.address, self.password, self.host, self.port = address, password, host, port
        self.conn = None
        self._labels_made = set()
        self._drafts = None

    def __enter__(self):
        self.conn = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=ssl.create_default_context())
        self.conn.login(self.address, self.password)
        self._ok(self.conn.select("INBOX"))
        return self

    def __exit__(self, *exc):
        try:
            self.conn.logout()
        except Exception:
            pass

    @staticmethod
    def _ok(result):
        typ, data = result
        if typ != "OK":
            raise RuntimeError(f"IMAP error: {data}")
        return data

    def search(self, query):
        data = self._ok(self.conn.uid("SEARCH", "X-GM-RAW", _quote(query)))
        return [u.decode() for u in (data[0] or b"").split()]

    def msgids(self, uids):
        """uid -> Gmail's stable message id, without downloading bodies."""
        out = {}
        for i in range(0, len(uids), 500):
            data = self._ok(self.conn.uid("FETCH", ",".join(uids[i:i + 500]), "(X-GM-MSGID)"))
            for item in data:
                head = item[0] if isinstance(item, tuple) else item
                if isinstance(head, bytes):
                    meta = _meta(head)
                    if "UID" in meta:
                        out[meta["UID"]] = meta.get("X-GM-MSGID", "")
        return out

    def fetch(self, uids, max_bytes=3_000_000):
        """max_bytes cuts off giant attachments; the parser tolerates the truncation."""
        emails = []
        spec = f"(X-GM-MSGID X-GM-THRID FLAGS BODY.PEEK[]<0.{int(max_bytes)}>)"
        for i in range(0, len(uids), FETCH_CHUNK):
            data = self._ok(self.conn.uid("FETCH", ",".join(uids[i:i + FETCH_CHUNK]), spec))
            for item in data:
                if isinstance(item, tuple) and len(item) >= 2:
                    meta = _meta(item[0])
                    ids = (meta.get("UID", ""), meta.get("X-GM-MSGID", ""), meta.get("X-GM-THRID", ""))
                    try:
                        emails.append(parse_message(item[1], *ids, meta["starred"]))
                    except Exception as e:  # one broken email must never stop a run
                        emails.append(unreadable_email(item[1], *ids, meta["starred"], e))
        return emails

    def headers(self, uids, progress=None, cancel=None):
        """Sender/subject/date/size for many messages without downloading bodies (fast scan)."""
        out = []
        spec = "(X-GM-MSGID RFC822.SIZE FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
        for i in range(0, len(uids), 500):
            if cancel is not None and cancel.is_set():
                break
            data = self._ok(self.conn.uid("FETCH", ",".join(uids[i:i + 500]), spec))
            for item in data:
                if isinstance(item, tuple) and len(item) >= 2:
                    meta = _meta(item[0])
                    size = re.search(rb"RFC822\.SIZE (\d+)", item[0])
                    out.append(header_info(item[1], meta, int(size.group(1)) if size else 0))
            if progress:
                progress(min(i + 500, len(uids)), len(uids))
        return out

    def add_label(self, uid, label):
        if label not in self._labels_made:
            self.conn.create(_quote(label))  # fails harmlessly if it exists
            self._labels_made.add(label)
        self._ok(self.conn.uid("STORE", uid, "+X-GM-LABELS", f"({_quote(label)})"))

    def remove_label(self, uid, label):
        self._ok(self.conn.uid("STORE", uid, "-X-GM-LABELS", f"({_quote(label)})"))

    def archive(self, uid):
        self._ok(self.conn.uid("STORE", uid, "-X-GM-LABELS", "(\\Inbox)"))

    def mark_read(self, uid):
        self._ok(self.conn.uid("STORE", uid, "+FLAGS", "(\\Seen)"))

    def star(self, uid):
        self._ok(self.conn.uid("STORE", uid, "+FLAGS", "(\\Flagged)"))

    def trash(self, uid):
        """Move to Gmail's Trash (recoverable for 30 days). Never expunges."""
        self._ok(self.conn.uid("STORE", uid, "+X-GM-LABELS", "(\\Trash)"))

    def drafts_folder(self):
        if self._drafts is None:
            self._drafts = "[Gmail]/Drafts"
            for line in self._ok(self.conn.list()):
                line = line.decode(errors="replace") if isinstance(line, bytes) else ""
                m = re.match(r'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$', line)
                if m and "\\Drafts" in m["flags"]:
                    self._drafts = m["name"].strip().strip('"')
                    break
        return self._drafts

    def save_draft(self, msg):
        self._ok(self.conn.append(
            _quote(self.drafts_folder()), "(\\Draft)",
            imaplib.Time2Internaldate(time.time()), msg.as_bytes(policy=email.policy.SMTP),
        ))


def send_smtp(address, password, msg, host="smtp.gmail.com", port=465):
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=60) as s:
        s.login(address, password)
        s.send_message(msg)
