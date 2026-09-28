#!/usr/bin/env bash
# Apply the CommonClaude harness to this repository (DevSpec section 0.2).
#
# The script is idempotent: it initialises the submodule, creates the
# harness files that are missing, and reports which hook dependencies
# and MCP servers are still absent. It never overwrites existing files
# and never edits anything inside external/CommonClaude.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
submodule_dir="$repo_root/external/CommonClaude"
required_mcp=(serena context7 fetch)
status=0

log() { printf '[setup_harness] %s\n' "$*"; }
warn() { printf '[setup_harness] WARNING: %s\n' "$*" >&2; status=1; }

# 1. Submodule must be initialised before anything else is usable.
if [[ ! -f "$submodule_dir/CLAUDE.md" ]]; then
    log "initialising external/CommonClaude submodule"
    git -C "$repo_root" submodule update --init --recursive
fi
log "submodule: $(git -C "$repo_root" submodule status -- external/CommonClaude)"

# 2. Create harness files that are missing. Existing files are kept
#    because CLAUDE.md and ToDo.md accumulate project history.
create_if_missing() {
    local path="$1"
    local rel="${path#"$repo_root"/}"
    if [[ -e "$path" ]]; then
        log "exists: $rel"
        cat > /dev/null
        return
    fi
    mkdir -p "$(dirname "$path")"
    cat > "$path"
    log "created: $rel"
}

create_if_missing "$repo_root/CLAUDE.md" <<'TEMPLATE'
@external/CommonClaude/CLAUDE.md

# Project Overrides: AutomatedGPUBenchmark
TEMPLATE

create_if_missing "$repo_root/ToDo.md" <<'TEMPLATE'
# ToDo

Append only. Never rewrite or reorder earlier entries.
TEMPLATE

create_if_missing "$repo_root/claude_test/README.md" <<'TEMPLATE'
# claude_test

| File | Purpose | What was learned |
|---|---|---|
TEMPLATE

if [[ ! -f "$repo_root/.claude/settings.json" ]]; then
    # Rewrite the hook paths so they resolve inside the submodule.
    mkdir -p "$repo_root/.claude"
    sed 's#"\$CLAUDE_PROJECT_DIR"/.claude/hooks/#"$CLAUDE_PROJECT_DIR"/external/CommonClaude/.claude/hooks/#g' \
        "$submodule_dir/.claude/settings.json" \
        > "$repo_root/.claude/settings.json"
    log "created: .claude/settings.json"
else
    log "exists: .claude/settings.json"
fi

# 3. Hook dependencies.
for tool in jq ruff; do
    if command -v "$tool" > /dev/null 2>&1; then
        log "found: $tool ($("$tool" --version 2>&1 | head -1))"
    else
        warn "$tool is not installed; hooks that need it will not run"
    fi
done

# 4. Required MCP servers (CommonClaude CLAUDE.md section 7).
if ! command -v claude > /dev/null 2>&1; then
    warn "claude CLI not found; cannot check MCP servers"
else
    mcp_list="$(claude mcp list 2>&1 || true)"
    for server in "${required_mcp[@]}"; do
        if grep -qi "^$server:" <<< "$mcp_list"; then
            log "mcp registered: $server"
        else
            warn "mcp missing: $server (see CommonClaude CLAUDE.md 7.3)"
        fi
    done
fi

if [[ "$status" -ne 0 ]]; then
    log "finished with warnings"
else
    log "harness complete"
fi
exit "$status"
