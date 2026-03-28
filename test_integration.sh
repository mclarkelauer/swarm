#!/usr/bin/env bash
#
# test_integration.sh — End-to-end integration test for all CLI improvements
#
# Runs through every new command and feature, verifies output, and cleans up.
# Uses a temp HOME so nothing touches your real ~/.swarm or working tree.
#
# Usage:
#   ./test_integration.sh          Run all tests
#   ./test_integration.sh --keep   Don't clean up temp dir on success
#
set -uo pipefail

KEEP=false
[[ "${1:-}" == "--keep" ]] && KEEP=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
if [[ -t 1 ]]; then
    GREEN='\033[0;32m' RED='\033[0;31m' DIM='\033[2m' BOLD='\033[1m' RESET='\033[0m'
else
    GREEN='' RED='' DIM='' BOLD='' RESET=''
fi

pass() { echo -e "  ${GREEN}✓${RESET} $*"; }
fail() { echo -e "  ${RED}✗${RESET} $*"; FAILURES=$((FAILURES + 1)); }
section() { echo -e "\n${BOLD}$*${RESET}"; }

FAILURES=0
TESTS=0

# Run a command, capture output and exit code without -e killing us
run_cmd() {
    set +e
    OUT=$("$@" 2>&1)
    EXIT_CODE=$?
    set -e
}

assert_contains() {
    local label="$1" expected="$2"
    TESTS=$((TESTS + 1))
    if echo "$OUT" | grep -qi "$expected"; then
        pass "$label"
    else
        fail "$label — expected '$expected' in output"
        echo -e "    ${DIM}$(echo "$OUT" | head -5)${RESET}"
    fi
}

assert_not_contains() {
    local label="$1" unexpected="$2"
    TESTS=$((TESTS + 1))
    if echo "$OUT" | grep -qi "$unexpected"; then
        fail "$label — did not expect '$unexpected' in output"
        echo -e "    ${DIM}$(echo "$OUT" | head -5)${RESET}"
    else
        pass "$label"
    fi
}

assert_exit_0() {
    local label="$1"
    TESTS=$((TESTS + 1))
    if [[ $EXIT_CODE -eq 0 ]]; then
        pass "$label"
    else
        fail "$label — exit code $EXIT_CODE"
    fi
}

assert_exit_nonzero() {
    local label="$1"
    TESTS=$((TESTS + 1))
    if [[ $EXIT_CODE -ne 0 ]]; then
        pass "$label"
    else
        fail "$label — expected nonzero exit code"
    fi
}

assert_file_exists() {
    local label="$1" path="$2"
    TESTS=$((TESTS + 1))
    if [[ -f "$path" ]]; then
        pass "$label"
    else
        fail "$label — file not found: $path"
    fi
}

assert_file_not_exists() {
    local label="$1" path="$2"
    TESTS=$((TESTS + 1))
    if [[ ! -f "$path" ]]; then
        pass "$label"
    else
        fail "$label — file should not exist: $path"
    fi
}

# Setup isolated environment with a fake HOME
TMPDIR="$(mktemp -d)"
FAKE_HOME="$TMPDIR/home"
mkdir -p "$FAKE_HOME"
export HOME="$FAKE_HOME"

PROJECT_DIR="$TMPDIR/project"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# Create the default config location (~/.swarm)
SWARM_DATA="$FAKE_HOME/.swarm"
mkdir -p "$SWARM_DATA/forge"
cat > "$SWARM_DATA/config.json" << 'EOF'
{"forge_timeout": 600}
EOF

swarm() { uv run --project "$SCRIPT_DIR" swarm "$@"; }

cleanup() {
    if $KEEP; then
        echo -e "\n${DIM}Temp dir kept at: $TMPDIR${RESET}"
    else
        rm -rf "$TMPDIR"
    fi
}
trap cleanup EXIT

echo -e "${BOLD}Swarm CLI Integration Tests${RESET}"
echo -e "${DIM}Temp dir: $TMPDIR${RESET}"

# =========================================================================
section "1. swarm ls — empty state"
# =========================================================================

run_cmd swarm ls
assert_exit_0 "ls exits cleanly"
assert_contains "ls shows empty message" "No agents or plans"

# =========================================================================
section "2. registry create — make some agents"
# =========================================================================

run_cmd swarm registry create --name code-reviewer --prompt "You review code for quality and bugs."
assert_exit_0 "create code-reviewer"
assert_contains "create shows name" "code-reviewer"

run_cmd swarm registry create --name api-tester --prompt "You write integration tests for REST APIs." --tools "Read,Grep"
assert_exit_0 "create api-tester"

run_cmd swarm registry create --name doc-writer --prompt "You write technical documentation."
assert_exit_0 "create doc-writer"

# =========================================================================
section "3. swarm ls — with agents"
# =========================================================================

run_cmd swarm ls
assert_exit_0 "ls with agents"
assert_contains "ls shows code-reviewer" "code-reviewer"
assert_contains "ls shows api-tester" "api-tester"
assert_contains "ls shows doc-writer" "doc-writer"

# =========================================================================
section "4. Name-based inspect"
# =========================================================================

run_cmd swarm registry inspect code-reviewer
assert_exit_0 "inspect by name"
assert_contains "inspect shows prompt" "review code"

run_cmd swarm registry inspect nonexistent-agent-xyz
assert_exit_nonzero "inspect nonexistent fails"

# =========================================================================
section "5. Name-based clone"
# =========================================================================

run_cmd swarm registry clone code-reviewer --name security-reviewer --prompt "You review code for security vulnerabilities."
assert_exit_0 "clone by name"
assert_contains "clone shows new name" "security-reviewer"

# =========================================================================
section "6. Search with provenance"
# =========================================================================

run_cmd swarm registry search review
assert_exit_0 "search works"
assert_contains "search finds code-reviewer" "code-reviewer"
assert_contains "search finds security-reviewer" "security-reviewer"

run_cmd swarm registry search nonexistent-zzz
assert_exit_0 "search no match"
assert_contains "search shows no match" "No agents"

# =========================================================================
section "7. Forge suggest with parent column"
# =========================================================================

run_cmd swarm forge suggest review
assert_exit_0 "suggest works"
assert_contains "suggest finds agents" "code-reviewer"

run_cmd swarm forge suggest zzzzz-no-match
assert_exit_0 "suggest no match"
assert_contains "suggest shows no match" "No agents"

# =========================================================================
section "8. Forge export"
# =========================================================================

EXPORT_FILE="$TMPDIR/exported.agent.json"
run_cmd swarm forge export code-reviewer -o "$EXPORT_FILE"
assert_exit_0 "export succeeds"
assert_file_exists "export creates file" "$EXPORT_FILE"

# Verify exported content
if [[ -f "$EXPORT_FILE" ]]; then
    TESTS=$((TESTS + 1))
    if python3 -c "
import json, sys
d = json.load(open('$EXPORT_FILE'))
assert 'name' in d, 'missing name'
assert 'system_prompt' in d, 'missing system_prompt'
assert 'id' not in d, 'should not have id'
assert 'created_at' not in d, 'should not have created_at'
assert 'source' not in d, 'should not have source'
" 2>&1; then
        pass "export excludes metadata"
    else
        fail "export content validation"
    fi
fi

run_cmd swarm forge export nonexistent-agent-xyz
assert_exit_nonzero "export nonexistent fails"

# =========================================================================
section "9. Forge import"
# =========================================================================

IMPORT_FILE="$TMPDIR/import-me.agent.json"
cat > "$IMPORT_FILE" << 'AGENT'
{
  "name": "imported-agent",
  "system_prompt": "I was imported from a file.",
  "tools": ["Read", "Write"],
  "permissions": ["read"]
}
AGENT

run_cmd swarm forge import "$IMPORT_FILE"
assert_exit_0 "import succeeds"
assert_contains "import shows name" "imported-agent"

run_cmd swarm registry inspect imported-agent
assert_exit_0 "imported agent is in registry"

BAD_IMPORT="$TMPDIR/bad-import.agent.json"
echo '{"system_prompt": "no name"}' > "$BAD_IMPORT"
run_cmd swarm forge import "$BAD_IMPORT"
assert_exit_nonzero "import without name fails"

# =========================================================================
section "10. Name-based remove"
# =========================================================================

run_cmd swarm registry remove api-tester
assert_exit_0 "remove by name"
assert_contains "remove confirms" "Removed"

run_cmd swarm registry remove nonexistent-agent-xyz
assert_exit_nonzero "remove nonexistent fails"

# =========================================================================
section "11. Plan create — dry run"
# =========================================================================

STEPS_FILE="$PROJECT_DIR/steps.json"
cat > "$STEPS_FILE" << 'STEPS'
[
  {"id": "research", "type": "task", "prompt": "Research the topic", "agent_type": "researcher"},
  {"id": "write", "type": "task", "prompt": "Write the document", "agent_type": "writer", "depends_on": ["research"]},
  {"id": "review", "type": "checkpoint", "prompt": "Review the draft", "depends_on": ["write"]}
]
STEPS

run_cmd swarm plan create --goal "Write a design doc" --steps-file "$STEPS_FILE" --dry-run
assert_exit_0 "plan create dry-run"
assert_contains "dry-run shows goal" "Write a design doc"
assert_contains "dry-run says not saved" "Dry run"
assert_file_not_exists "dry-run doesn't create file" "$PROJECT_DIR/plan_v1.json"

# =========================================================================
section "12. Plan create — actual save"
# =========================================================================

run_cmd swarm plan create --goal "Write a design doc" --steps-file "$STEPS_FILE" --dir "$PROJECT_DIR"
assert_exit_0 "plan create saves"
assert_contains "create shows saved" "Saved"
assert_file_exists "plan file created" "$PROJECT_DIR/plan_v1.json"

# =========================================================================
section "13. Plan create — invalid steps"
# =========================================================================

BAD_STEPS="$TMPDIR/bad-steps.json"
echo '[{"id": "s1", "type": "invalid", "prompt": "bad"}]' > "$BAD_STEPS"
run_cmd swarm plan create --goal "Bad plan" --steps-file "$BAD_STEPS"
assert_exit_nonzero "invalid plan fails"
assert_contains "shows errors" "error"

# =========================================================================
section "14. Plan create — with variables"
# =========================================================================

VARS_FILE="$TMPDIR/vars.json"
echo '{"language": "python"}' > "$VARS_FILE"
run_cmd swarm plan create --goal "Versioned plan" --steps-file "$STEPS_FILE" --variables "$VARS_FILE" --dir "$PROJECT_DIR"
assert_exit_0 "plan create with variables"
assert_file_exists "plan v2 created" "$PROJECT_DIR/plan_v2.json"

# =========================================================================
section "15. Plan list — rich output"
# =========================================================================

run_cmd swarm plan list --dir "$PROJECT_DIR"
assert_exit_0 "plan list"
assert_contains "list shows v1" "plan_v1"
assert_contains "list shows v2" "plan_v2"
assert_contains "list shows goal" "design doc"

# =========================================================================
section "16. swarm ls — with agents and plans"
# =========================================================================

run_cmd swarm ls
assert_exit_0 "ls with everything"
assert_contains "ls shows agents" "code-reviewer"
assert_contains "ls shows plans" "design doc"

# =========================================================================
section "17. Plan resume"
# =========================================================================

PLAN_FILE="$PROJECT_DIR/plan_v1.json"

run_cmd swarm plan resume "$PLAN_FILE"
assert_exit_0 "resume no completed"
assert_contains "resume shows first step" "research"

run_cmd swarm plan resume "$PLAN_FILE" --completed research
assert_exit_0 "resume after research"
assert_contains "resume shows write step" "write"

run_cmd swarm plan resume "$PLAN_FILE" --completed research,write
assert_exit_0 "resume after write"
assert_contains "resume shows review step" "review"

run_cmd swarm plan resume "$PLAN_FILE" --completed research,write,review
assert_exit_0 "resume all complete"
assert_contains "resume says complete" "complete"

# =========================================================================
section "18. swarm run — auto-confirm all steps"
# =========================================================================

RUN_STEPS="$TMPDIR/run-steps.json"
cat > "$RUN_STEPS" << 'RUNSTEPS'
[
  {"id": "s1", "type": "task", "prompt": "Step one", "agent_type": "worker"},
  {"id": "s2", "type": "task", "prompt": "Step two", "agent_type": "worker", "depends_on": ["s1"]}
]
RUNSTEPS
swarm plan create --goal "Run test" --steps-file "$RUN_STEPS" --dir "$PROJECT_DIR" >/dev/null 2>&1
RUN_PLAN="$PROJECT_DIR/plan_v3.json"

set +e
OUT=$(yes 2>/dev/null | swarm run "$RUN_PLAN" 2>&1)
EXIT_CODE=$?
# yes causes SIGPIPE (141) when swarm exits — treat 0 or 141 as success
if [[ $EXIT_CODE -eq 141 ]]; then EXIT_CODE=0; fi
set -e

assert_exit_0 "run completes"
assert_contains "run says complete" "complete"
assert_file_exists "run creates log" "$PROJECT_DIR/run_log.json"

# Verify run log content
if [[ -f "$PROJECT_DIR/run_log.json" ]]; then
    TESTS=$((TESTS + 1))
    if python3 -c "
import json
d = json.load(open('$PROJECT_DIR/run_log.json'))
assert d['status'] == 'completed', f'expected completed, got {d[\"status\"]}'
ids = {s['step_id'] for s in d['steps'] if s['status'] == 'completed'}
assert 's1' in ids, 's1 not completed'
assert 's2' in ids, 's2 not completed'
" 2>&1; then
        pass "run log has both steps completed"
    else
        fail "run log content validation"
    fi
fi

# =========================================================================
section "19. swarm run — decline at first step (pause)"
# =========================================================================

rm -f "$PROJECT_DIR/run_log.json"
set +e
OUT=$(echo "n" | swarm run "$RUN_PLAN" 2>&1)
EXIT_CODE=$?
set -e
assert_exit_0 "run pause exits cleanly"
assert_contains "run shows paused" "Paused"

# =========================================================================
section "20. swarm run — resume from --completed"
# =========================================================================

rm -f "$PROJECT_DIR/run_log.json"
set +e
OUT=$(yes 2>/dev/null | swarm run "$RUN_PLAN" --completed s1 2>&1)
EXIT_CODE=$?
if [[ $EXIT_CODE -eq 141 ]]; then EXIT_CODE=0; fi
set -e
assert_exit_0 "run with --completed"
assert_contains "run completes from resume" "complete"

# =========================================================================
section "21. swarm run — invalid plan"
# =========================================================================

BAD_PLAN="$TMPDIR/bad-plan.json"
echo '{"version": 1, "goal": "", "steps": []}' > "$BAD_PLAN"
run_cmd swarm run "$BAD_PLAN"
assert_exit_nonzero "run invalid plan fails"

# =========================================================================
section "22. Project agent catalog — sync"
# =========================================================================

mkdir -p "$PROJECT_DIR/.swarm/agents"
cat > "$PROJECT_DIR/.swarm/agents/local-agent.agent.json" << 'LOCALAGENT'
{"name": "local-agent", "system_prompt": "I am a project-local agent.", "tools": ["Read"], "permissions": []}
LOCALAGENT
cat > "$PROJECT_DIR/.swarm/agents/another-agent.agent.json" << 'ANOTHER'
{"name": "another-agent", "system_prompt": "Another local agent.", "tools": [], "permissions": []}
ANOTHER

run_cmd swarm sync --dir "$PROJECT_DIR"
assert_exit_0 "sync imports agents"
assert_contains "sync imports local-agent" "local-agent"
assert_contains "sync imports another-agent" "another-agent"
assert_contains "sync shows count" "2 imported"

# =========================================================================
section "23. Sync — skip already registered"
# =========================================================================

run_cmd swarm sync --dir "$PROJECT_DIR"
assert_exit_0 "sync skips existing"
assert_contains "sync shows already registered" "Already registered"
assert_contains "sync shows 0 imported" "0 imported"

# =========================================================================
section "24. Sync — no agents dir"
# =========================================================================

EMPTY_PROJECT="$TMPDIR/empty-project"
mkdir -p "$EMPTY_PROJECT"
run_cmd swarm sync --dir "$EMPTY_PROJECT"
assert_exit_0 "sync no agents dir"
assert_contains "sync says no dir" "No .swarm/agents"

# =========================================================================
section "25. Verify synced agents are in registry"
# =========================================================================

run_cmd swarm registry inspect local-agent
assert_exit_0 "synced agent is inspectable"
assert_contains "synced agent has prompt" "project-local"

# =========================================================================
section "26. Plan validate"
# =========================================================================

run_cmd swarm plan validate "$PLAN_FILE"
assert_exit_0 "validate valid plan"
assert_contains "validate says valid" "valid"

run_cmd swarm plan validate "$BAD_PLAN"
assert_exit_nonzero "validate invalid plan fails"

# =========================================================================
section "27. Plan show"
# =========================================================================

run_cmd swarm plan show "$PLAN_FILE"
assert_exit_0 "show works"
assert_contains "show displays goal" "design doc"
assert_contains "show displays steps" "research"

# =========================================================================
section "28. Registry list"
# =========================================================================

run_cmd swarm registry list
assert_exit_0 "registry list"
assert_contains "list shows code-reviewer" "code-reviewer"
assert_contains "list shows imported-agent" "imported-agent"
assert_contains "list shows local-agent" "local-agent"
assert_not_contains "list doesn't show removed api-tester" "api-tester"

# =========================================================================
section "29. Export → Import round-trip"
# =========================================================================

RT_FILE="$TMPDIR/roundtrip.agent.json"
swarm forge export security-reviewer -o "$RT_FILE" >/dev/null 2>&1
swarm registry remove security-reviewer >/dev/null 2>&1
run_cmd swarm forge import "$RT_FILE"
assert_exit_0 "round-trip import"

run_cmd swarm registry inspect security-reviewer
assert_exit_0 "round-trip agent exists"
assert_contains "round-trip prompt preserved" "security"

# =========================================================================
# Summary
# =========================================================================

echo
echo "==========================================="
if [[ $FAILURES -eq 0 ]]; then
    echo -e "${GREEN}${BOLD}ALL $TESTS TESTS PASSED${RESET}"
else
    echo -e "${RED}${BOLD}$FAILURES OF $TESTS TESTS FAILED${RESET}"
fi
echo "==========================================="

exit $FAILURES
