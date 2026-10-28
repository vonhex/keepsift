# Contributing to KeepSift

Thanks for helping! Bug reports, false-positive/negative examples for the safety net, model
recommendations, docs and code are all welcome.

## Ground rules

- **Never post real email content, addresses, passwords or app passwords** in issues or pull
  requests. Make up test data; the `.eml` files in `samples/` show the format.
- Security problems go through private reporting; see [SECURITY.md](SECURITY.md).
- Be kind: this project follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Running from source

Requires Windows and Python 3.11+.

```
Setup.bat                      # creates .venv, installs requirements, adds shortcuts
.venv\Scripts\python -m keepsift.gui
.venv\Scripts\python -m keepsift --help
```

The core logic (`protect.py`, `cleanup.py`, `agent.py`, `mail.py`) is plain standard-library
Python and runs on any OS; only the GUI is Windows-focused.

## Tests

```
python -m unittest discover -s tests -v
```

The tests need no Gmail account and no model server. They run on every push and pull request.

**If you change `keepsift/protect.py`, add a test.** The deletion safety net is the part of
KeepSift where a bug costs people their email, so every pull request that touches it should show:

- what new thing is now protected (or what false alarm is now avoided), and
- that the existing protected samples are still kept. `tests/test_protect.py` already checks this.

## Pull requests

1. Fork, create a branch, make your change.
2. Run the tests.
3. Keep the style of the surrounding code: standard library first, short functions, comments only
   where something isn't obvious.
4. Describe *why* in the pull request, and include before/after screenshots for UI changes.

## License of contributions

KeepSift is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE): free for any
non-commercial use, not for sale. By submitting a contribution you agree it is licensed under the
same terms, and that you have the right to license it.
