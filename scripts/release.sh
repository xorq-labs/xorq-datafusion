#!/bin/bash
# Prepare a release commit: steps 1-6 of the Release Flow in CONTRIBUTING.md.
#
# Usage:
#   bash scripts/release.sh <major|minor|patch>
#
# Starts a release-$version branch from the main branch of the release remote,
# bumps the version in Cargo.toml and Cargo.lock, updates CHANGELOG.md with
# git-cliff, pauses for manual notes, and commits "release: $version".
# Nothing is pushed; the remaining steps are printed at the end.
#
# The release remote is $RELEASE_REMOTE if set, else `upstream` if that remote
# exists, else `origin`.
set -euo pipefail

usage() {
    echo "Usage: $0 <major|minor|patch>" >&2
    exit 2
}

[ $# -eq 1 ] || usage
bump_type="$1"
case "$bump_type" in
    major | minor | patch) ;;
    *) usage ;;
esac

cd "$(git rev-parse --show-toplevel)"

if [ -n "${RELEASE_REMOTE:-}" ]; then
    remote="$RELEASE_REMOTE"
elif git remote | grep -qx upstream; then
    remote=upstream
else
    remote=origin
fi

if ! git diff --quiet HEAD --; then
    echo "Error: tracked files have uncommitted changes; commit or stash them first." >&2
    exit 1
fi

# Step 1: start from the release remote's main
echo "Step 1: Fetching $remote/main..."
git fetch "$remote" main
base="$remote/main"

# Step 2: compute the new version number according to Semantic Versioning
current=$(git show "$base:Cargo.toml" | sed -n 's/^version = "\(.*\)"$/\1/p' | head -n 1)
if ! [[ "$current" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    echo "Error: cannot parse version '$current' from Cargo.toml on $base." >&2
    exit 1
fi
major="${BASH_REMATCH[1]}" minor="${BASH_REMATCH[2]}" patch="${BASH_REMATCH[3]}"
case "$bump_type" in
    major) version="$((major + 1)).0.0" ;;
    minor) version="$major.$((minor + 1)).0" ;;
    patch) version="$major.$minor.$((patch + 1))" ;;
esac
echo "Step 2: $current -> $version"

# Step 3: create the release branch from the remote main
echo "Step 3: Creating branch release-$version from $base..."
git switch --no-track --create="release-$version" "$base"

# Step 4: update the version in Cargo.toml (first `version =` line is the
# [package] one) and let cargo rewrite the lockfile entry for this crate.
echo "Step 4: Updating Cargo.toml and Cargo.lock..."
awk -v old="version = \"$current\"" -v new="version = \"$version\"" \
    '!done && $0 == old { print new; done = 1; next } { print }' \
    Cargo.toml >Cargo.toml.tmp
mv Cargo.toml.tmp Cargo.toml
cargo update --workspace --offline --quiet

# Step 5: update the CHANGELOG
echo "Step 5: Updating CHANGELOG.md..."
git cliff --github-repo xorq-labs/xorq-datafusion -p CHANGELOG.md --tag "v$version" -u
echo
echo "CHANGELOG updated. Add any additional notes (blog posts, links, etc.) manually, then press Enter to continue..."
read -r

# Step 6: create the release commit
echo "Step 6: Creating release commit..."
git add --update
git commit -m "release: $version"

cat <<EOF

Release commit created on release-$version. Next steps (CONTRIBUTING.md, 7-13):
  git push --set-upstream $remote release-$version
  open a PR for release-$version
  run ci-pre-release from branch release-$version and wait for it to pass
  squash and merge the PR
  git fetch $remote && git tag v$version $remote/main && git push $remote v$version
  create a GitHub release for v$version to publish
EOF
