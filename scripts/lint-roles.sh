#!/usr/bin/env bash
# lint-roles.sh -- Validate role markdown files for the open-foundry project.
#
# Usage:
#   scripts/lint-roles.sh                    # lint all role files
#   scripts/lint-roles.sh roles/software/backend_engineer.md  # lint one file
#
# Checks performed on each role file:
#   1. Frontmatter exists (opening and closing ---)
#   2. name: field present and is snake_case
#   3. expertise: field present and non-empty
#   4. name: value matches filename (without .md)
#   5. Body (after frontmatter) has >= 150 words
#   6. Body contains a section about evaluating/analyzing proposals
#   7. Body contains "What you are NOT" or "you are NOT" section
#
# Skips roles/orchestrator/ files (different format).
# Exits 0 if all files pass, 1 if any fail.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

failures=0
checked=0

lint_file() {
    local filepath="$1"
    local relpath="${filepath#"$REPO_ROOT"/}"
    local filename
    filename="$(basename "$filepath" .md)"

    # Skip orchestrator roles (different format) and synthesizer (utility role)
    if [[ "$relpath" == roles/orchestrator/* ]]; then
        return 0
    fi
    if [[ "$filename" == "synthesizer" ]]; then
        return 0
    fi

    checked=$((checked + 1))
    local file_failed=0

    # Read the file content
    local content
    content="$(cat "$filepath")"

    # --- Check 1: Frontmatter exists (opening and closing ---) ---
    local first_line
    first_line="$(head -n 1 "$filepath")"
    if [[ "$first_line" != "---" ]]; then
        echo "FAIL  $relpath: missing frontmatter (no opening ---)"
        file_failed=1
    fi

    # Find the closing --- (second occurrence, must be on its own line)
    local closing_line=0
    local line_num=0
    while IFS= read -r line; do
        line_num=$((line_num + 1))
        if [[ "$line" == "---" && $line_num -gt 1 ]]; then
            closing_line=$line_num
            break
        fi
    done < "$filepath"

    if [[ $closing_line -eq 0 ]]; then
        echo "FAIL  $relpath: missing frontmatter (no closing ---)"
        file_failed=1
        # Cannot proceed without frontmatter
        if [[ $file_failed -ne 0 ]]; then
            failures=$((failures + 1))
            return 0
        fi
    fi

    # Extract frontmatter (between line 2 and closing_line - 1)
    local frontmatter
    frontmatter="$(sed -n "2,$((closing_line - 1))p" "$filepath")"

    # Extract body (everything after closing ---)
    local body
    body="$(tail -n +"$((closing_line + 1))" "$filepath")"

    # --- Check 2: name: field present and is snake_case ---
    local name_value
    name_value="$(echo "$frontmatter" | sed -n 's/^name: *//p')"
    if [[ -z "$name_value" ]]; then
        echo "FAIL  $relpath: missing 'name:' field in frontmatter"
        file_failed=1
    elif ! echo "$name_value" | grep -qE '^[a-z][a-z_]*$'; then
        echo "FAIL  $relpath: name '$name_value' is not snake_case (lowercase letters and underscores only)"
        file_failed=1
    fi

    # --- Check 3: expertise: field present and non-empty ---
    local expertise_value
    expertise_value="$(echo "$frontmatter" | sed -n 's/^expertise: *//p')"
    if [[ -z "$expertise_value" ]]; then
        echo "FAIL  $relpath: missing or empty 'expertise:' field in frontmatter"
        file_failed=1
    fi

    # --- Check 4: name: value matches filename without .md ---
    if [[ -n "$name_value" && "$name_value" != "$filename" ]]; then
        echo "FAIL  $relpath: name '$name_value' does not match filename '$filename'"
        file_failed=1
    fi

    # --- Check 5: Body has >= 150 words ---
    local word_count
    word_count="$(echo "$body" | wc -w | tr -d ' ')"
    if [[ "$word_count" -lt 150 ]]; then
        echo "FAIL  $relpath: body has $word_count words (minimum 150)"
        file_failed=1
    fi

    # --- Check 6: Body contains evaluation/analysis section ---
    if ! echo "$body" | grep -qiE 'When (evaluating|analyzing|assessing|reviewing)'; then
        echo "FAIL  $relpath: missing evaluation/analysis section (expected 'When evaluating/analyzing/assessing/reviewing')"
        file_failed=1
    fi

    # --- Check 7: Body contains "What you are NOT" or "you are NOT" ---
    if ! echo "$body" | grep -qiE '(What you are NOT|you are NOT|You do NOT)'; then
        echo "FAIL  $relpath: missing negative space section (expected 'What you are NOT' or 'you are NOT' or 'You do NOT')"
        file_failed=1
    fi

    # Report result
    if [[ $file_failed -eq 0 ]]; then
        echo "PASS  $relpath"
    else
        failures=$((failures + 1))
    fi
}

# Determine which files to lint
if [[ $# -gt 0 ]]; then
    # Lint specific files passed as arguments
    for f in "$@"; do
        if [[ -f "$f" ]]; then
            lint_file "$(cd "$(dirname "$f")" && pwd)/$(basename "$f")"
        else
            echo "FAIL  $f: file not found"
            failures=$((failures + 1))
        fi
    done
else
    # Lint all role files, skipping orchestrator
    while IFS= read -r -d '' f; do
        lint_file "$f"
    done < <(find "$REPO_ROOT/roles" -name '*.md' -print0 | sort -z)
fi

echo ""
echo "Checked $checked file(s): $((checked - failures)) passed, $failures failed."

if [[ $failures -gt 0 ]]; then
    exit 1
fi
exit 0
