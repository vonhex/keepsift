# Security policy

KeepSift handles two sensitive things: your **Gmail app password** and the **content of your
email**. Security reports are very welcome.

## Supported versions

Only the latest release gets fixes. Please update before reporting.

| Version | Supported |
|---|---|
| latest release | yes |
| older releases | no |

## Reporting a vulnerability

**Please don't open a public issue for security problems.** Report privately instead:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**. GitHub keeps the report private between you and the maintainer.

Include what you found, how to reproduce it, and which version and setup you used. **Don't include
real email content, passwords or app passwords**; make up test data instead.

KeepSift is a free, volunteer-run project, so responses are best-effort. You should get an
acknowledgement within about a week. Once a fix is released you'll be credited, unless you'd
rather not be.

## What counts

Examples of things we want to hear about:

- The Gmail login (`.env`) or email content leaking anywhere other than Gmail and the model server
  you configured: logs, crash output, network calls, the GitHub-built exe.
- An email that can make KeepSift **send** mail, change settings, or act beyond what the user's
  settings allow (prompt injection that defeats the auto-send guardrails).
- A way to make the deletion safety net remove an email it should protect (for example a crafted
  email that hides a product key or activation link from `keepsift/protect.py`). These are also
  fine as normal issues if no real data is involved.
- Problems in the release build or GitHub Actions workflow that could ship a tampered exe.

Out of scope: weaknesses of the model itself, issues that need an already-compromised PC, and
problems in Gmail, Python or your model server (report those upstream).

## Good practice for users

- Use a Gmail **app password**, never your main password, and revoke it in your Google account
  if you stop using KeepSift.
- `.env` holds that app password in plain text: keep the KeepSift folder private, and never share
  it or commit it anywhere.
- Point KeepSift only at a model server you control. Everything you clean or sort is sent to it.
