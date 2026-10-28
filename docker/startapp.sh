#!/bin/sh
# Started by the base image as the app user; restarted automatically if it exits.
export HOME=/config
cd /app || exit 1
exec python3 -m keepsift.gui
