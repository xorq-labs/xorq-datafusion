#!/bin/bash
# Measure the local Rust edit/build iteration cycle on the current checkout.
#
# Usage:
#   bash scripts/bench-build.sh [--rounds N] [--clean]
#
#   --rounds N   repetitions per scenario (default 3)
#   --clean      also run `cargo clean` and time a cold `cargo build --lib`
#                (throws away the whole target/ cache; off by default)
#
# Run it from a shell where .envrc is loaded (direnv), so bare cargo sees the
# same PyO3 variables maturin exports. To compare two branches, run the same
# script on each. The script lives on the branch under test, so pull it out of
# git when measuring main:
#
#   git switch chore/faster-dev-builds && bash scripts/bench-build.sh
#   git show chore/faster-dev-builds:scripts/bench-build.sh > /tmp/bench-build.sh
#   git switch main && bash /tmp/bench-build.sh
#
# The warm-up step absorbs the one-off rebuild caused by switching branches
# with a different dev profile, so only steady-state numbers are reported.
#
# Scenarios:
#   alternate   maturin develop -> cargo build --lib -> cargo clippy (via the
#               pre-commit hook) -> maturin develop, with no source change.
#               Every step should be a no-op; without the PyO3 variables each
#               step recompiles pyo3 and everything above it.
#   edit        append a one-line function to src/utils.rs, run
#               `maturin develop`, remove it, run `maturin develop` again.
#   sizes       size of the debug .so and of the debug target directory.
set -euo pipefail

rounds=3
clean=0
while [ $# -gt 0 ]; do
    case "$1" in
        --rounds) rounds="${2:-}"; shift 2 || shift ;;
        --clean) clean=1; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
case "$rounds" in
    '' | *[!0-9]* | 0) echo "--rounds needs a positive integer, got '$rounds'" >&2; exit 2 ;;
esac

# Keep `uv run` from syncing (and rebuilding the project) inside timed steps.
export UV_NO_SYNC=1

cd "$(git rev-parse --show-toplevel)"
src=src/utils.rs
backup=$(mktemp)
log=$(mktemp)
cp "$src" "$backup"
# Copy back only if the file differs, so a clean exit does not bump the
# mtime and force a rebuild on the next cargo invocation.
trap 'cmp -s "$backup" "$src" || cp "$backup" "$src"; rm -f "$backup" "$log"' EXIT

# Run the hook itself so the benchmark follows any change to its flags.
clippy_cmd=(uv run pre-commit run rust-clippy --all-files)

# fail <command...>: report a failed step with its output, then exit.
fail() {
    echo "  FAILED: $*" >&2
    tail -n 40 "$log" >&2
    exit 1
}

# quiet <command...>: run with output captured to the log.
quiet() {
    "$@" >"$log" 2>&1 || fail "$@"
}

# timed <label> <command...>: run quietly, print wall seconds. Uses the
# `time` keyword so it works with the bash 3.2 that ships with macOS.
timed() {
    local label="$1"; shift
    local secs TIMEFORMAT=%R
    secs=$( { time "$@" >"$log" 2>&1; } 2>&1 ) || fail "$@"
    printf '  %-34s %6.2f s\n' "$label" "$secs"
}

echo "branch: $(git branch --show-current)  commit: $(git rev-parse --short HEAD)"
echo "rustc: $(rustc --version)"
echo "PYO3_ENVIRONMENT_SIGNATURE: ${PYO3_ENVIRONMENT_SIGNATURE:-<unset>}"
echo

if [ "$clean" -eq 1 ]; then
    echo "clean build (cargo clean first)"
    quiet cargo clean
    timed "cargo build --lib (cold)" cargo build --lib
    echo
fi

echo "warm-up (not measured)"
quiet uv run maturin develop --uv
quiet cargo build --lib
quiet "${clippy_cmd[@]}"
quiet uv run maturin develop --uv
echo

echo "alternate: no source change, maturin <-> bare cargo"
for ((i = 1; i <= rounds; i++)); do
    echo " round $i"
    timed "maturin develop --uv" uv run maturin develop --uv
    timed "cargo build --lib" cargo build --lib
    timed "cargo clippy (pre-commit hook)" "${clippy_cmd[@]}"
    timed "maturin develop --uv" uv run maturin develop --uv
done
echo

echo "edit: one-line change in $src, then maturin develop"
for ((i = 1; i <= rounds; i++)); do
    echo " round $i"
    printf '\n#[allow(dead_code)]\nfn __bench_probe_%d() -> u32 {\n    %d\n}\n' "$i" "$i" >>"$src"
    timed "add fn + maturin develop --uv" uv run maturin develop --uv
    cp "$backup" "$src"
    timed "remove fn + maturin develop --uv" uv run maturin develop --uv
done
echo

echo "sizes"
debug_dir="${CARGO_TARGET_DIR:-target}/debug"
so=$(find python/xorq_datafusion -maxdepth 1 -name '_internal*.so' | head -n 1)
if [ -n "$so" ]; then
    printf '  %-34s %6.1f MB\n' "installed .so" "$(awk "BEGIN{print $(wc -c <"$so")/1048576}")"
else
    printf '  %-34s %s\n' "installed .so" "not found"
fi
if [ -d "$debug_dir" ]; then
    printf '  %-34s %s\n' "$debug_dir" "$(du -sh "$debug_dir" | cut -f1)"
else
    printf '  %-34s %s\n' "$debug_dir" "not found"
fi
