<p align="center">
  <img src="assets/icon-256.png" width="112" alt="KeepSift logo">
</p>

<h1 align="center">KeepSift</h1>

<p align="center">
  <b>Clean out a huge Gmail inbox with your own local AI, without ever losing a product key, activation link or receipt.</b><br>
  Windows desktop app · runs against any OpenAI-compatible model server · nothing goes to a cloud AI
</p>

<p align="center">
  <a href="../../releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/vonhex/keepsift"></a>
  <a href="../../actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/vonhex/keepsift/actions/workflows/tests.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: PolyForm Noncommercial" src="https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue"></a>
</p>

<p align="center">
  <img src="docs/cleanup-dark.png" width="860" alt="KeepSift cleanup screen">
</p>

> [!WARNING]
> **KeepSift deletes email. Read [Before you clean anything](#before-you-clean-anything) first.**
> Small local models make mistakes, and the safety net lowers the risk without removing it.
> KeepSift comes with **no warranty and no liability for lost or deleted email**.

## Why

Gmail already splits mail into Promotions, Social and Updates, but years of it pile up into tens
of thousands of emails nobody will ever read. Deleting them in bulk is scary: somewhere in there is
a software license key, a "confirm your account" link or a receipt you'll need.

KeepSift lets you clear the pile **sender by sender**, and puts every single email through a safety
net first. Your AI model runs on your own hardware, so your mail stays private.

## Features

- **Bulk cleanup**: scans Gmail's tabs, groups mail by sender (biggest first), and removes what you
  pick. Choose a "To Delete" label to review in Gmail, or Trash, which is recoverable for 30 days.
  Nothing is ever permanently deleted.
- **A safety net that isn't the AI**: fixed rules in the code (`keepsift/protect.py`) always keep:
  - product, license, serial and activation keys, game and gift-card codes, and anything key-shaped
    like `ABCDE-12345-FGHIJ`
  - activation, verification, sign-in, download and reset links, including link targets hidden in
    HTML buttons
  - 2FA and recovery codes, and security alerts
  - receipts, orders and invoices; attachments; starred mail; emails too large to check
  - your own protected words and senders

  An optional model double-check then catches the things rules can't recognise, like personal
  messages.
- **Sort new mail**: labels, priorities, phishing and prompt-injection flags, and reply drafts
  saved to Gmail Drafts for you to review. Auto-send is off by default and fenced in by an
  allowlist and send limits.
- **Made to be left running**: Watch mode with quiet hours, a Stop button (or Esc) that halts
  cleanly between emails, and progress saved as it goes, so big jobs can be stopped and resumed.
- **Every setting has a form** with an explanation: categories, rules, prompts, labels, safety
  limits. There's also a raw config page if you want it.
- **Light and dark mode** with a Windows 11 look.

<p align="center">
  <img src="docs/home-dark.png" width="420" alt="Home dashboard">
  <img src="docs/settings-light.png" width="420" alt="Settings">
</p>

## Get started

You need two things: **Windows 10/11** and **a local AI model server** (see below).

**Option A: download the app.** Grab `KeepSift.exe` from the
[latest release](../../releases/latest) and run it. Nothing to install; settings are kept in
`%LOCALAPPDATA%\KeepSift`.

**Option B: run from source.** Download or clone this repo and double-click **`Setup.bat`**.
It installs Python if needed, sets everything up, adds Desktop and Start-menu shortcuts and opens
KeepSift.

Either way, a short setup wizard opens on first launch:

1. **Connect Gmail.** Create a Gmail [app password](https://myaccount.google.com/apppasswords)
   (needs 2-Step Verification) and paste it in. Your normal password is never used.
2. **Find your model.** "Find my model automatically" checks the usual local ports, or you can type
   your server's address.
3. **About you.** Your name and sign-off, used for reply drafts.

Then open **Cleanup**, click **Scan inbox**, pick some obvious junk senders, tick
**Preview only**, and see what KeepSift would keep before running it for real.

### Your model server

KeepSift talks to any **OpenAI-compatible** endpoint, on the same PC or elsewhere on your network:

| Server | Typical address |
|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server` | `http://localhost:8080/v1` |
| [LM Studio](https://lmstudio.ai) | `http://localhost:1234/v1` |
| [Ollama](https://ollama.com) | `http://localhost:11434/v1` |
| vLLM and others | `http://localhost:8000/v1` |

It uses JSON-schema structured output (`response_format`), so the server needs to support that.
Development was done against a Qwen-family model on a llama.cpp-style server. Other servers and
models should work but are less tested.

### Which model? Size matters

The model decides what each email is, whether it's worth keeping, and what a reply should say.
**Small models are noticeably worse at all three.** They misread emails, miss things worth
keeping, and follow instructions hidden in emails more easily. Bigger and newer is safer.

| Your GPU memory | Size to aim for | Example models (instruction-tuned, ~4-bit quantised) |
|---|---|---|
| under 8 GB | not recommended | Below ~7B parameters, use cleanup with the model check **off** (rules only) and review everything yourself |
| 8–12 GB | 7–14B (minimum) | Qwen3 8B, Llama 3.1 8B Instruct, Gemma 3 12B |
| 16–24 GB | 14–32B (recommended) | Qwen3 14B, Qwen3 30B-A3B, Mistral Small 3.2 24B, Gemma 3 27B, gpt-oss 20B |
| 32 GB and up | 30B+ (best) | Qwen3 32B, larger Qwen MoE models, Llama 3.3 70B |

These are examples, not endorsements: newer releases of these families generally work better
still. Whatever you pick, run **Test emails → Run included samples** first. It should flag the
phishing and prompt-injection samples as suspicious, and keep the product-key and Steam-code ones.

## Before you clean anything

- **Nothing here is perfect.** The keyword and link rules catch the common cases (keys, codes,
  activation links, receipts), but an important email that matches none of them, judged wrong by
  the model, can be removed.
- **Start with "Label 'To Delete'"**, not Trash, and look through the label in Gmail before deleting.
- **Use "Preview only"** on a few senders first, and read what it would keep in the Activity tab.
- **Trash is only a 30-day safety net.** Gmail permanently empties its Trash after 30 days, and
  after that KeepSift can't bring anything back.
- **Back up first** if your mail matters: [Google Takeout](https://takeout.google.com) can export
  your whole mailbox.
- **Watch the "Kept" list.** Every kept email has a reason in the Activity tab. If something
  important was *removed*, add its sender or a word from it under Settings → Deletion so it's
  protected next time.

### No warranty, no liability

KeepSift is provided free of charge, **"as is", without warranty of any kind** (see [LICENSE](LICENSE)).
You run it on your own mailbox at your own risk. **The authors and contributors are not liable for
any lost, deleted, mislabelled or wrongly sent email**, or any other damage from using it. You are
responsible for checking what it does, keeping backups, and choosing settings that suit you.

## How cleanup decides

```
Gmail tab + age filter ──► group by sender ──► you pick senders
                                                     │
          every email ◄──────────────────────────────┘
               │
   too big / starred? ──yes──► keep
               │ no
   keys, codes, activation links, receipts,
   attachments, protected words/senders?  ──yes──► keep (labelled "Kept - Important")
               │ no
   model double-check (optional): worth keeping? ──yes──► keep
               │ no
   label "To Delete"  or  move to Trash (30-day undo)
```

Progress is saved per email, so a rescan only shows what's left.

## Command line

`KeepSift.bat` with arguments runs the command-line tool:

```
KeepSift.bat check                      # test model + Gmail
KeepSift.bat run --dry-run              # sort new mail, change nothing
KeepSift.bat run --live                 # sort new mail for real
KeepSift.bat watch --live               # keep sorting every few minutes
KeepSift.bat try samples\*.eml          # try the model on sample emails, offline
KeepSift.bat log -n 30                  # what was done and why
```

## Privacy

- Email content only ever goes to the model server **you** configure.
- Your Gmail login is stored locally in `.env` (or `%LOCALAPPDATA%\KeepSift\.env` for the exe).
  App passwords can be revoked at any time in your Google account.
- Gmail is reached directly over IMAP/SMTP. There's no KeepSift server and no telemetry.

## Building the exe

`build_exe.bat` produces `dist\KeepSift.exe` with PyInstaller. Pushing a `v*` tag builds it on
GitHub Actions and attaches it to a release.

## Contributing and security

Bug reports and safety-net examples are very welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Please report security problems privately, as described in
[SECURITY.md](SECURITY.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

[PolyForm Noncommercial License 1.0.0](LICENSE). **Free to use, copy and modify for any
non-commercial purpose**: personal use, hobby projects, research, charities, schools and public
bodies. **Not for sale and not for commercial use**: you may not sell KeepSift, charge for it, or
use it in or for a paid product or service. Because of that it's "source-available" rather than
OSI open source. Versions v1.0.0 and v1.0.1 were released under MIT; copies of those you already
have keep those terms.
