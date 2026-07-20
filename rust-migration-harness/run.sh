#!/usr/bin/env bash
# rust-migration-harness entry point.
#
# Exits 0 ONLY when every suite passes (i.e. the Rust migration is
# behaviourally complete). Until the Rust workspace exists, the rust-*
# suites report "Rust implementation missing" and the run exits non-zero.
#
# Environment knobs:
#   SKIP_SELFCHECK=1   skip the python self-check suites (e.g. after the
#                      python tree has been removed post-migration)
#   SKIP_SLOW=1        pass --skip-slow to the behavioral suites
#   RUST_DIR=...       override the cargo workspace dir (default: rust/)
set -u

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$HARNESS_DIR")"
RUST_DIR="${RUST_DIR:-$REPO_ROOT/rust}"
VECTOR_CHECK="$RUST_DIR/target/debug/cbus-vector-check"
RUST_CMQTTD="$RUST_DIR/target/debug/cmqttd"

VENV_PY="$REPO_ROOT/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then VENV_PY="$(command -v python3 || true)"; fi

BEHAVE_ARGS=()
if [ "${SKIP_SLOW:-0}" = "1" ]; then BEHAVE_ARGS+=("--skip-slow"); fi

declare -a SUITE_NAMES=()
declare -a SUITE_RESULTS=()
FAIL=0

record() {  # name, status-string, is_failure(0/1)
  SUITE_NAMES+=("$1")
  SUITE_RESULTS+=("$2")
  if [ "$3" = "1" ]; then FAIL=1; fi
}

banner() { echo; echo "=== $1 ==="; }

# ---------------------------------------------------------------- selfcheck
have_cbus=0
if [ -n "$VENV_PY" ] && "$VENV_PY" -c 'import cbus' 2>/dev/null; then
  have_cbus=1
fi

if [ "${SKIP_SELFCHECK:-0}" = "1" ]; then
  record "selfcheck-vectors"    "SKIP (SKIP_SELFCHECK=1)" 0
  record "selfcheck-behavioral" "SKIP (SKIP_SELFCHECK=1)" 0
elif [ "$have_cbus" = "0" ]; then
  record "selfcheck-vectors"    "SKIP (python cbus package unavailable)" 0
  record "selfcheck-behavioral" "SKIP (python cbus package unavailable)" 0
else
  banner "selfcheck-vectors (python vs committed vectors)"
  if out=$("$VENV_PY" "$HARNESS_DIR/suites/verify_vectors.py" 2>&1); then
    echo "$out"
    record "selfcheck-vectors" "$(echo "$out" | tail -1 | sed 's/^selfcheck-vectors: //')" 0
  else
    echo "$out"
    record "selfcheck-vectors" "FAIL" 1
  fi

  banner "selfcheck-behavioral (python cmqttd vs harness)"
  if "$VENV_PY" "$HARNESS_DIR/suites/behavioral.py" --impl python "${BEHAVE_ARGS[@]+"${BEHAVE_ARGS[@]}"}"; then
    record "selfcheck-behavioral" "PASS" 0
  else
    record "selfcheck-behavioral" "FAIL" 1
  fi
fi

# --------------------------------------------------------------------- rust
banner "rust-build (cargo build --workspace)"
if [ ! -f "$RUST_DIR/Cargo.toml" ]; then
  echo "Rust implementation missing: no Cargo workspace at $RUST_DIR"
  record "rust-build"        "FAIL (Rust implementation missing)" 1
  record "protocol-vectors"  "FAIL (Rust implementation missing)" 1
  record "rust-unit-tests"   "FAIL (Rust implementation missing)" 1
  record "behavioral-cmqttd" "FAIL (Rust implementation missing)" 1
else
  if (cd "$RUST_DIR" && cargo build --workspace); then
    record "rust-build" "PASS" 0
  else
    record "rust-build" "FAIL" 1
  fi

  banner "protocol-vectors (cbus-vector-check)"
  if [ ! -x "$VECTOR_CHECK" ]; then
    echo "expected binary not found: $VECTOR_CHECK"
    record "protocol-vectors" "FAIL (cbus-vector-check missing)" 1
  elif out=$("$VECTOR_CHECK" "$HARNESS_DIR/vectors" 2>&1); then
    echo "$out" | tail -5
    summary=$(echo "$out" | tail -1)
    record "protocol-vectors" "$summary" 0
  else
    echo "$out" | tail -30
    record "protocol-vectors" "FAIL" 1
  fi

  banner "rust-unit-tests (cargo test --workspace)"
  if (cd "$RUST_DIR" && cargo test --workspace); then
    record "rust-unit-tests" "PASS" 0
  else
    record "rust-unit-tests" "FAIL" 1
  fi

  banner "behavioral-cmqttd (rust cmqttd vs harness)"
  if [ -n "$VENV_PY" ]; then
    "$VENV_PY" "$HARNESS_DIR/suites/behavioral.py" --impl rust \
        --rust-bin "$RUST_CMQTTD" "${BEHAVE_ARGS[@]+"${BEHAVE_ARGS[@]}"}"
    rc=$?
    if [ $rc -eq 0 ]; then
      record "behavioral-cmqttd" "PASS" 0
    elif [ $rc -eq 3 ]; then
      record "behavioral-cmqttd" "FAIL (Rust cmqttd binary missing)" 1
    else
      record "behavioral-cmqttd" "FAIL" 1
    fi
  else
    record "behavioral-cmqttd" "FAIL (no python3 available to drive harness)" 1
  fi
fi

# --------------------------------------------------------------- scoreboard
echo
echo "==================== SCOREBOARD ===================="
for i in "${!SUITE_NAMES[@]}"; do
  printf '  %-22s %s\n' "${SUITE_NAMES[$i]}:" "${SUITE_RESULTS[$i]}"
done
echo "===================================================="
if [ "$FAIL" = "0" ]; then
  echo "RESULT: FULL SUCCESS"
  exit 0
else
  echo "RESULT: FAILURE (migration incomplete)"
  exit 1
fi
