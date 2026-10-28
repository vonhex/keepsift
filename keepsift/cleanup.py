"""Bulk inbox cleanup: scan Gmail's categories by sender, then trash/label what is safe to remove.

Every email still passes protect.email_blockers() (keys, activation links, attachments, starred,
protected senders...) and optionally the model's keep-check before anything happens to it.
"""
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import config
from .agent import keep_check
from .protect import email_blockers, learn_boilerplate

LEARN_MIN = 5  # senders with at least this many selected emails get their footer learned


def scan(cfg, store, gmail, categories, older_than_days, report=print, cancel=None, recheck_kept=False):
    """Headers for every email in the chosen Gmail categories, grouped by sender (biggest first).

    Returns (groups, already_done) where each group is
    {"sender", "name", "count", "category", "newest", "example", "items": [header dicts]}.
    recheck_kept: also list emails a previous cleanup kept, so they're checked again.
    """
    items = {}
    for cat in categories:
        if cancel is not None and cancel.is_set():
            break
        q = f"category:{cat}" + (f" older_than:{older_than_days}d" if older_than_days else "")
        uids = gmail.search(q)
        report(f"{cat}: {len(uids)} emails, reading senders...")
        for h in gmail.headers(uids, cancel=cancel):
            h["category"] = cat
            items.setdefault(h["gm_msgid"] or h["uid"], h)
    done = store.cleanup_seen(items, exclude_kept=recheck_kept)
    groups = {}
    for key, h in items.items():
        if key in done:
            continue
        g = groups.setdefault(h["from_addr"], {"sender": h["from_addr"], "name": h["from_name"], "items": []})
        g["items"].append(h)
    out = []
    for g in groups.values():
        its = sorted(g["items"], key=lambda h: h["date"], reverse=True)
        g.update(count=len(its), newest=its[0]["date"], example=its[0]["subject"],
                 category=Counter(h["category"] for h in its).most_common(1)[0][0], items=its)
        out.append(g)
    out.sort(key=lambda g: g["count"], reverse=True)
    return out, len(done & set(items))


def _batches(items, size):
    """Big senders get batches of their own (so their footer can be learned); small ones share."""
    by_sender = {}
    for h in items:
        by_sender.setdefault(h["from_addr"], []).append(h)
    pooled = []
    for sender, hs in by_sender.items():
        if len(hs) >= LEARN_MIN:
            for i in range(0, len(hs), size):
                yield sender, hs[i:i + size]
        else:
            pooled += hs
    for i in range(0, len(pooled), size):
        yield None, pooled[i:i + size]


def clean(cfg, llm, store, gmail, items, action, use_model, preview=False,
          report=print, progress=None, cancel=None):
    """Check and remove `items` (header dicts from scan). Returns counts.

    action: "trash" (Gmail Trash, recoverable 30 days) or "label" (label 'To Delete' for review).
    preview: check everything but change nothing and record nothing.
    """
    c, d = cfg["cleanup"], cfg["deletion"]
    stopped = lambda: cancel is not None and cancel.is_set()
    counts = Counter()
    total, started = len(items), time.time()
    cap = c["max_size_kb"] * 1024
    kept_label = config.label(cfg, d["protected_label_name"])
    delete_label = config.label(cfg, d["label_name"])
    footers = {}  # sender -> lines/links that repeat in all their emails

    def keep(h, reasons):
        counts["kept"] += 1
        report(f"  kept  {h['from_addr']} | {h['subject'][:60]}  ({'; '.join(reasons)})")
        if not preview:
            if c["label_kept"]:
                gmail.add_label(h["uid"], kept_label)
            store.record_cleanup(h["gm_msgid"], h["from_addr"], h["subject"], "kept", reasons)

    def check(em):
        """Runs in a worker thread: content rules first, then (optionally) the model."""
        if stopped():
            return em, None, None
        try:
            reasons = email_blockers(cfg, em, footers.get(em.from_addr, frozenset()))
            if not reasons and use_model:
                wanted, why = keep_check(llm, cfg, em)
                if wanted:
                    reasons = [f"model: {why or 'worth keeping'}"]
            return em, reasons, None
        except Exception as e:
            return em, None, e

    with ThreadPoolExecutor(max_workers=max(1, cfg["llm"]["parallel"])) as pool:
        for sender, batch in _batches(items, max(LEARN_MIN, c["batch_size"])):
            if stopped():
                break
            by_uid = {h["uid"]: h for h in batch}
            small = []
            for h in batch:
                if h["size"] > cap:
                    keep(h, [f"too big to check fully ({h['size'] // 1024} KB)"])
                elif h["starred"] and d["protect_starred"]:
                    keep(h, ["is starred"])
                else:
                    small.append(h["uid"])
            emails = gmail.fetch(small, cap + 1) if small else []
            if sender and sender not in footers and len(emails) >= LEARN_MIN:
                footers[sender] = learn_boilerplate(cfg, [e for e in emails if e.from_addr == sender])
                if footers[sender]:
                    report(f"  ({sender}: ignoring {len(footers[sender])} footer line(s)/link(s) that repeat "
                           f"in every email, e.g. {next(iter(footers[sender]))[:70]!r})")
            for em, reasons, err in pool.map(check, emails):
                if stopped():
                    break
                h = by_uid.get(em.uid, {"uid": em.uid, "gm_msgid": em.gm_msgid,
                                        "from_addr": em.from_addr, "subject": em.subject})
                if err:
                    counts["failed"] += 1  # not recorded: it's retried next time
                    report(f"  !     {h['from_addr']} | {h['subject'][:60]}  (check failed: {err})")
                elif reasons:
                    keep(h, reasons)
                else:
                    counts["removed"] += 1
                    if not preview:
                        if action == "trash":
                            gmail.trash(h["uid"])
                        else:
                            gmail.add_label(h["uid"], delete_label)
                            gmail.remove_label(h["uid"], kept_label)  # may carry it from an earlier run
                        store.record_cleanup(h["gm_msgid"], h["from_addr"], h["subject"],
                                             "trashed" if action == "trash" else "marked", [])
            if progress:
                done = sum(counts.values())
                rate = (time.time() - started) / max(1, done)
                progress(done, total, counts, rate * (total - done))

    verb = {"trash": "moved to Trash", "label": "labelled To Delete"}[action]
    if preview:
        verb = "would be " + verb
    tail = "Stopped early; " if stopped() else ""
    report(f"\n{tail}{counts['removed']} {verb}, {counts['kept']} kept, {counts['failed']} failed "
           f"({(time.time() - started) / 60:.1f} min).")
    return counts
