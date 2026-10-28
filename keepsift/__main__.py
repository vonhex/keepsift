"""CLI: python -m keepsift {check,run,watch,try,log}"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from . import agent, config
from .llm import LLM
from .mail import Gmail, parse_message
from .store import Store


def cmd_check(cfg, args):
    llm = LLM(cfg["llm"])
    print("LLM models:", ", ".join(llm.ping()))
    acct = cfg["account"]
    with Gmail(acct["address"], acct["password"], acct["imap_host"], acct["imap_port"]) as g:
        uids = g.search(acct["query"])
        print(f"Gmail login OK as {acct['address']}; {len(uids)} messages match '{acct['query']}'")
        print("Drafts folder:", g.drafts_folder())


def _dry(cfg, args):
    if args.live:
        return False
    if args.dry_run:
        return True
    return cfg["safety"]["dry_run"]


def cmd_run(cfg, args):
    acct = cfg["account"]
    store = Store(cfg["db_path"])
    with Gmail(acct["address"], acct["password"], acct["imap_host"], acct["imap_port"]) as g:
        agent.run(cfg, LLM(cfg["llm"]), store, g, _dry(cfg, args), args.limit, args.query)


def cmd_watch(cfg, args):
    interval = args.interval or cfg["watch"]["interval_minutes"] * 60
    print(f"Watching every {interval}s. Ctrl+C to stop.")
    while True:
        print(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===")
        try:
            cfg = config.load(args.config)  # pick up settings changed in the GUI
            if agent.quiet_now(cfg):
                print("Quiet hours: skipping this run.")
            else:
                cmd_run(cfg, args)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # network blips, Gmail throttling, LLM down: retry next cycle
            print(f"Run failed: {e}", file=sys.stderr)
        time.sleep(interval)


def cmd_try(cfg, args):
    """Classify (and draft) a local .eml file. Nothing touches Gmail."""
    llm = LLM(cfg["llm"])
    for path in args.files:
        print(f"\n### {path}")
        agent.explain(llm, cfg, parse_message(Path(path).read_bytes()), args.draft)


def cmd_log(cfg, args):
    for r in Store(cfg["db_path"]).recent(args.n):
        print(f"{r['processed_at']}  [{r['category']}/{r['priority']}] {r['sender']} | "
              f"{(r['subject'] or '')[:60]}  reply={r['reply_action']}")
        print(f"    {r['summary']}")


def main():
    p = argparse.ArgumentParser(prog="keepsift", description="KeepSift: local-AI Gmail cleanup and triage")
    p.add_argument("--config", help="path to config.toml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="test the LLM and Gmail connections")

    for name in ("run", "watch"):
        s = sub.add_parser(name, help="process new mail once" if name == "run" else "process new mail in a loop")
        mode = s.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="only show what would happen")
        mode.add_argument("--live", action="store_true", help="override safety.dry_run = true")
        s.add_argument("--limit", type=int, help="max messages this run")
        s.add_argument("--query", help="Gmail search query (default from config)")
        if name == "watch":
            s.add_argument("--interval", type=int, help="seconds between runs (default: watch.interval_minutes)")

    s = sub.add_parser("try", help="classify local .eml files without touching Gmail")
    s.add_argument("files", nargs="+")
    s.add_argument("--draft", action="store_true", help="always generate a draft")

    s = sub.add_parser("log", help="show recent decisions")
    s.add_argument("-n", type=int, default=20)

    args = p.parse_args()
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        stream.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load(args.config)
    try:
        {"check": cmd_check, "run": cmd_run, "watch": cmd_watch, "try": cmd_try, "log": cmd_log}[args.cmd](cfg, args)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
