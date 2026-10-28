# Changelog

## Unreleased

- License changed from MIT to the **PolyForm Noncommercial License 1.0.0**: free for any
  non-commercial use; selling KeepSift or using it in a paid product isn't allowed. Copies already
  received under v1.0.0 or v1.0.1 stay under MIT.
- Added a security policy, contributing guide, code of conduct, issue and pull-request templates,
  automated tests (safety net, parsing, cleanup) and a CI workflow that runs them.
- Docker image `ghcr.io/vonhex/keepsift` (the app in a browser tab via noVNC) and an Unraid template.
- New setting: start watching automatically when KeepSift opens (for servers and containers).
- `KEEPSIFT_MODEL_URL` pre-fills the model server address in containers.

## v1.0.1

- Warnings in the README, setup wizard and cleanup confirmation: local model size and quality,
  recommended models by GPU memory, a checklist before cleaning, and no warranty or liability for
  deleted email.

## v1.0.0

- First release: bulk cleanup by sender with a rule-based safety net, sender-footer learning,
  sorting and reply drafts with a local OpenAI-compatible model, setup wizard, light/dark UI,
  Setup.bat and a standalone exe.
