#!/usr/bin/env bash
# Offline cmqttd deployment rehearsal (docs/deployment-rehearsal.md).
#
# Builds candidate and previous cmqttd images from clean `git archive`
# contexts, starts an isolated staging stack (cmqttd + Mosquitto + the Rust
# PCI simulator) under a unique compose project, and exercises:
#   1. discovery/state/command checks after first start
#   2. broker kill + restart: resubscription and discovery republish
#   3. simulator (CNI) TCP drop: exit + supervisor restart recovery
#   4. rollback to the previous image on the same state volume, then
#      roll forward to the candidate
# and always tears everything down. It never touches the production stack:
# no fixed container names, no published ports, no .env, no real endpoints.
#
# Usage: deploy/staging/rehearse.sh [--dry-run]
# Env:   CANDIDATE_REV (default HEAD), PREVIOUS_REV (default HEAD~1),
#        PREVIOUS_IMAGE (reuse an existing tag instead of building
#        PREVIOUS_REV), RECEIPT (receipt path), KEEP_IMAGES=1,
#        EXPECT_SIM_CONFIRM_GAP (default 0; set 1 only when an image under
#        test predates CR-terminated from-PCI framing, which lost PCI
#        confirmations after the simulator's basic-mode echo; see
#        docs/deployment-rehearsal.md).
set -euo pipefail

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
elif [ $# -gt 0 ]; then
    echo "usage: $0 [--dry-run]" >&2
    exit 2
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
COMPOSE_FILE="$HERE/docker-compose.staging.yml"
RUN_ID="$(date -u +%Y%m%dt%H%M%Sz)-$$"
export STAGING_PROJECT="cbus-staging-$RUN_ID"
CANDIDATE_REV="${CANDIDATE_REV:-HEAD}"
PREVIOUS_REV="${PREVIOUS_REV:-HEAD~1}"
CANDIDATE_TAG="cmqttd-staging:${RUN_ID}-candidate"
PREVIOUS_TAG="${PREVIOUS_IMAGE:-cmqttd-staging:${RUN_ID}-previous}"
RECEIPT="${RECEIPT:-${TMPDIR:-/tmp}/${STAGING_PROJECT}-receipt.txt}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/${STAGING_PROJECT}.XXXXXX")"
FAILURES=0
EXPECT_SIM_CONFIRM_GAP="${EXPECT_SIM_CONFIRM_GAP:-0}"

# Never let a typo aim compose at the production project.
case "$STAGING_PROJECT" in
    cbus-staging-*) ;;
    *) echo "refusing unsafe project name $STAGING_PROJECT" >&2; exit 2 ;;
esac

log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*" | tee -a "$RECEIPT"; }
record() { printf '%s\n' "$*" >>"$RECEIPT"; }
pass() { if [ "$DRY_RUN" = 1 ]; then log "DRY $*"; else log "PASS $*"; fi; }
fail() { log "FAIL $*"; FAILURES=$((FAILURES + 1)); }
# A confirmation check: a hard check by default. With EXPECT_SIM_CONFIRM_GAP=1
# (a pre-fix image) it is XFAIL, or XPASS when it passes anyway.
known_gap() {
    local ok=$1; shift
    if [ "$EXPECT_SIM_CONFIRM_GAP" = 1 ]; then
        if [ "$DRY_RUN" = 1 ]; then log "DRY XFAIL-expected $*"
        elif [ "$ok" = 1 ]; then log "XPASS $* (gap fixed? set EXPECT_SIM_CONFIRM_GAP=0)"; else log "XFAIL $*"; fi
    elif [ "$ok" = 1 ]; then
        pass "$*"
    else
        fail "$*"
    fi
}

# Run with a wall-clock limit (macOS has no coreutils timeout).
limit() { local seconds=$1; shift; perl -e 'alarm shift; exec @ARGV' "$seconds" "$@"; }

run() {
    if [ "$DRY_RUN" = 1 ]; then
        local shown="$*"
        printf '+ %s\n' "${shown//$REPO/.}" | tee -a "$RECEIPT"
        return 0
    fi
    "$@"
}

dc() {
    run docker compose -p "$STAGING_PROJECT" -f "$COMPOSE_FILE" "$@"
}

# Retained broker contents as "topic payload" lines.
retained() {
    if [ "$DRY_RUN" = 1 ]; then
        printf '+ mosquitto_sub --retained-only homeassistant/#\n' >>"$RECEIPT"
        return 0
    fi
    dc exec -T broker mosquitto_sub -h localhost -t 'homeassistant/#' \
        --retained-only -v -W 3 2>/dev/null || true
}

# Wait until retained topic $1 has payload matching ERE $2.
await_retained() {
    local topic=$1 pattern=$2 deadline=$((SECONDS + ${3:-60}))
    [ "$DRY_RUN" = 1 ] && { retained >/dev/null; return 0; }
    while [ $SECONDS -lt $deadline ]; do
        if retained | grep -E -q "^${topic} ${pattern}\$"; then
            return 0
        fi
        sleep 2
    done
    return 1
}

# Commands cmqttd parsed so far (proves the /set wildcard subscription).
parsed_commands() {
    dc logs --no-color cmqttd 2>/dev/null | grep -c "command parsed: GA=$1," || true
}

# Publish a /set command. Returns 0 when cmqttd received it; sets
# CONFIRMED=1 when its command_result reported a confirmed delivery.
CONFIRMED=0
command_roundtrip() {
    local group=$1 state=$2
    CONFIRMED=0
    if [ "$DRY_RUN" = 1 ]; then
        run mosquitto_pub -t "homeassistant/light/cbus_${group}/set" -m "{\"state\": \"${state}\"}"
        CONFIRMED=$((1 - EXPECT_SIM_CONFIRM_GAP))
        return 0
    fi
    local out="$WORK/result-$group-$state-$SECONDS" before sub deadline
    before="$(parsed_commands "$group")"
    dc exec -T broker mosquitto_sub -h localhost -t cmqttd/cbus/command_result \
        -C 1 -W 30 >"$out" 2>/dev/null &
    sub=$!
    sleep 1
    dc exec -T broker mosquitto_pub -h localhost \
        -t "homeassistant/light/cbus_${group}/set" -m "{\"state\": \"${state}\"}"
    wait "$sub" || true
    grep -q '"delivery":"confirmed"' "$out" && CONFIRMED=1
    deadline=$((SECONDS + 10))
    while [ $SECONDS -lt $deadline ]; do
        [ "$(parsed_commands "$group")" -gt "$before" ] && return 0
        sleep 1
    done
    return 1
}

# Retained light and binary-sensor state lines, sorted.
light_states() {
    [ "$DRY_RUN" = 1 ] && { retained >/dev/null; return 0; }
    retained | grep -E '^homeassistant/(light|binary_sensor)/cbus_[0-9_]+/state ' | sort || true
}

restart_count() {
    [ "$DRY_RUN" = 1 ] && { echo 0; return; }
    docker inspect -f '{{.RestartCount}}' "$(dc ps -q cmqttd)"
}

running_image() {
    [ "$DRY_RUN" = 1 ] && { echo dry-run; return; }
    docker inspect -f '{{.Image}}' "$(dc ps -q cmqttd)"
}

state_hash() {
    [ "$DRY_RUN" = 1 ] && { echo dry-run; return; }
    dc exec -T cmqttd sh -c \
        'if [ -f /var/lib/cmqttd/cgate.json ]; then sha256sum /var/lib/cmqttd/cgate.json | cut -d" " -f1; else echo absent; fi'
}

cgate_banner() {
    [ "$DRY_RUN" = 1 ] && return 0
    # Wait for the greeting before sending QUIT, and allow for listener
    # startup after a (re)start.
    local deadline=$((SECONDS + 30))
    while [ $SECONDS -lt $deadline ]; do
        # Capture first: `grep -q` exiting early would SIGPIPE the exec
        # and fail the pipeline under pipefail.
        local greeting
        greeting="$(dc exec -T cmqttd sh -c '(sleep 1; printf "quit\r\n") | nc -w 3 127.0.0.1 20023' 2>/dev/null || true)"
        if printf '%s\n' "$greeting" | grep '^201 ' >/dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

baseline_checks() {
    local label=$1
    if await_retained 'homeassistant/binary_sensor/cbus_cmqttd/state' 'ON' 90; then
        pass "$label: bridge state retained ON"
    else
        fail "$label: bridge state not ON"
    fi
    if await_retained 'homeassistant/light/cbus_1/config' '\{.*\}' 30 \
        && await_retained 'homeassistant/binary_sensor/cbus_cmqttd/config' '\{.*\}' 5; then
        pass "$label: discovery retained"
    else
        fail "$label: discovery missing"
    fi
    if command_roundtrip 1 ON; then
        pass "$label: /set command received by cmqttd"
    else
        fail "$label: /set command not received"
    fi
    known_gap "$CONFIRMED" "$label: command delivery confirmed by the PCI"
    if cgate_banner; then
        pass "$label: C-Gate listener banner"
    else
        fail "$label: C-Gate listener banner missing"
    fi
}

teardown() {
    local code=$?
    log "teardown"
    if [ "$DRY_RUN" = 0 ]; then
        dc logs --no-color >"$WORK/compose.log" 2>&1 || true
    fi
    dc down -v --remove-orphans >/dev/null 2>&1 || true
    if [ "${KEEP_IMAGES:-0}" != 1 ]; then
        run docker image rm "$CANDIDATE_TAG" >/dev/null 2>&1 || true
        if [ -z "${PREVIOUS_IMAGE:-}" ]; then
            run docker image rm "$PREVIOUS_TAG" >/dev/null 2>&1 || true
        fi
    fi
    record "failures=$FAILURES exit=$code"
    echo "logs: $WORK"
    echo "receipt: $RECEIPT"
}

build_image() {
    local rev=$1 tag=$2 sha
    sha="$(git -C "$REPO" rev-parse "$rev^{commit}")"
    log "build $tag from $sha"
    if [ "$DRY_RUN" = 1 ]; then
        run sh -c "git archive $sha | docker build --build-arg CMQTTD_REVISION=$sha -t $tag -"
        return 0
    fi
    # A clean archive keeps ignored site files, .env and credentials out of
    # the build context regardless of the working tree.
    git -C "$REPO" archive --format=tar "$sha" \
        | docker build -q --build-arg "CMQTTD_REVISION=$sha" -t "$tag" - >/dev/null
    record "image $tag $(docker image inspect -f '{{.Id}}' "$tag") revision=$sha"
}

: >"$RECEIPT"
record "cmqttd staging rehearsal run=$RUN_ID dry_run=$DRY_RUN"
record "project=$STAGING_PROJECT candidate_rev=$(git -C "$REPO" rev-parse "$CANDIDATE_REV") previous=${PREVIOUS_IMAGE:-$(git -C "$REPO" rev-parse "$PREVIOUS_REV")}"

if [ "$DRY_RUN" = 0 ] && ! limit 20 docker info >/dev/null 2>&1; then
    log "docker daemon unavailable; rerun with --dry-run or start Docker first"
    exit 3
fi
trap teardown EXIT

build_image "$CANDIDATE_REV" "$CANDIDATE_TAG"
if [ -z "${PREVIOUS_IMAGE:-}" ]; then
    build_image "$PREVIOUS_REV" "$PREVIOUS_TAG"
fi
export STAGING_SIMULATOR_IMAGE="$CANDIDATE_TAG"

# 1. First start on the candidate image.
export STAGING_CMQTTD_IMAGE="$CANDIDATE_TAG"
log "phase 1: start candidate"
dc up -d
baseline_checks candidate
STATE_BEFORE="$(state_hash)"
record "cgate_state_sha256 candidate=$STATE_BEFORE"

# 2. Broker crash and restart (persistence disabled: retained state is lost).
log "phase 2: broker kill + restart"
STATES_BEFORE="$(light_states)"
record "light_states_before_broker_kill $(printf '%s' "$STATES_BEFORE" | grep -c . || true)"
dc kill broker
dc start broker
if await_retained 'homeassistant/binary_sensor/cbus_cmqttd/state' 'ON' 60 \
    && await_retained 'homeassistant/light/cbus_1/config' '\{.*\}' 30; then
    pass "broker restart: discovery and bridge state republished"
else
    fail "broker restart: discovery not republished"
fi
# On MQTT reconnect cmqttd republishes exactly the light state it had
# published from bus observations and confirmed command echoes, and
# fabricates none. The simulator answers no lighting status sweep, so the
# periodic -S resync adds nothing here.
[ "$DRY_RUN" = 1 ] || sleep "${STAGING_STATUS_RESYNC:-20}"
if [ "$(light_states)" = "$STATES_BEFORE" ]; then
    pass "broker restart: observed light state republished, none fabricated"
else
    fail "broker restart: retained light state differs from before the kill"
fi
if command_roundtrip 1 ON; then
    pass "broker restart: command wildcard resubscribed"
else
    fail "broker restart: command after restart not received"
fi

# 3. CNI TCP drop: plain -t mode exits and the supervisor restarts it.
log "phase 3: simulator TCP drop"
RESTARTS_BEFORE="$(restart_count)"
dc restart simulator
DEADLINE=$((SECONDS + 90))
RESTARTS_AFTER="$RESTARTS_BEFORE"
while [ "$DRY_RUN" = 0 ] && [ $SECONDS -lt $DEADLINE ]; do
    RESTARTS_AFTER="$(restart_count)"
    [ "$RESTARTS_AFTER" -gt "$RESTARTS_BEFORE" ] && break
    sleep 2
done
record "cmqttd_restart_count before=$RESTARTS_BEFORE after=$RESTARTS_AFTER"
if [ "$DRY_RUN" = 1 ] || [ "$RESTARTS_AFTER" -gt "$RESTARTS_BEFORE" ]; then
    pass "CNI drop: supervisor restarted cmqttd"
else
    fail "CNI drop: no supervisor restart observed"
fi
baseline_checks "after CNI drop"

# 4. Rollback to the previous image on the same state volume, then forward.
log "phase 4: rollback to $PREVIOUS_TAG"
export STAGING_CMQTTD_IMAGE="$PREVIOUS_TAG"
dc up -d --no-deps cmqttd
record "running_image rollback=$(running_image)"
baseline_checks rollback
STATE_ROLLBACK="$(state_hash)"
record "cgate_state_sha256 rollback=$STATE_ROLLBACK"

log "phase 4b: roll forward to $CANDIDATE_TAG"
export STAGING_CMQTTD_IMAGE="$CANDIDATE_TAG"
dc up -d --no-deps cmqttd
record "running_image forward=$(running_image)"
baseline_checks "roll forward"
STATE_FORWARD="$(state_hash)"
record "cgate_state_sha256 forward=$STATE_FORWARD"
if [ "$STATE_BEFORE" = "$STATE_FORWARD" ]; then
    pass "state volume survived rollback and roll forward"
else
    fail "state volume changed across rollback ($STATE_BEFORE -> $STATE_FORWARD)"
fi

if [ "$FAILURES" -gt 0 ]; then
    exit 1
fi
