#!/bin/sh
# Regenerates the repo-root CLAUDE.md from docs/CLAUDE_CONTEXT.md.
#
# CLAUDE_CONTEXT.md is the source of truth (its own relative links assume
# it lives inside docs/, pointing at sibling folders like ./Database/...).
# CLAUDE.md is a derived copy at the repo root, with every relative link
# rewritten to the ./docs/ prefix, kept there only so Claude Code auto-loads
# it on session startup.
#
# Run this from the repo root after editing docs/CLAUDE_CONTEXT.md:
#   sh scripts/sync-claude-md.sh
#
# Do NOT inline this command as literal text inside CLAUDE_CONTEXT.md itself
# -- its own docs/-prefixed link pattern will match the sed rule below and
# get double-prefixed on the next regeneration. Reference this script by
# name instead.

set -e
cd "$(dirname "$0")/.."

SRC="docs/CLAUDE_CONTEXT.md"
DST="CLAUDE.md"

sed -E 's#\]\(\./#](./docs/#g' "$SRC" | sed '1s/.*/# CLAUDE.md/' > "$DST"

echo "Regenerated $DST from $SRC."
