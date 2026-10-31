#!/usr/bin/env bash
# Fetch the pinned Archify development tool into the git-ignored .tools folder.
# Archify is not an application dependency; the generated HTML is committed.
set -euo pipefail

ARCHIFY_VERSION="3.2.0"
ARCHIFY_COMMIT="a4065941f12be7967436261d9934784e381d423c"
ARCHIFY_REPO="https://github.com/tt-a1i/archify"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/.tools/archify"
CLI="$DEST/archify/bin/archify.mjs"

command -v git >/dev/null 2>&1 || {
  echo "error: git is required" >&2
  exit 1
}
command -v node >/dev/null 2>&1 || {
  echo "error: Node.js 18 or newer is required" >&2
  exit 1
}

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "error: Node.js 18 or newer is required (found $(node --version))" >&2
  exit 1
fi
echo "Node $(node --version) found."

if [ -d "$DEST/.git" ]; then
  CURRENT="$(git -C "$DEST" rev-parse HEAD)"
  if [ "$CURRENT" = "$ARCHIFY_COMMIT" ]; then
    echo "Archify $ARCHIFY_VERSION is already present at $ARCHIFY_COMMIT."
  else
    echo "Updating Archify checkout from $CURRENT to $ARCHIFY_COMMIT..."
    git -C "$DEST" fetch --depth 1 origin "$ARCHIFY_COMMIT"
    git -C "$DEST" checkout --detach "$ARCHIFY_COMMIT"
  fi
else
  mkdir -p "$ROOT/.tools"
  echo "Cloning $ARCHIFY_REPO into $DEST..."
  git clone "$ARCHIFY_REPO" "$DEST"
  git -C "$DEST" checkout --detach "$ARCHIFY_COMMIT"
fi

ACTUAL="$(git -C "$DEST" rev-parse HEAD)"
if [ "$ACTUAL" != "$ARCHIFY_COMMIT" ]; then
  echo "error: expected $ARCHIFY_COMMIT, found $ACTUAL" >&2
  exit 1
fi

echo "Archify $ARCHIFY_VERSION pinned at $ACTUAL"
echo "CLI: $CLI"
node "$CLI" doctor
