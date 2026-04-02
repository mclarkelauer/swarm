#!/bin/bash
# Install Swarm skill to Claude Code

set -e

SKILL_DIR="$HOME/.claude/skills/swarm"

echo "Installing Swarm skill to Claude Code..."

# Create skill directory if it doesn't exist
mkdir -p "$SKILL_DIR"

# Copy skill file
cp "$(dirname "$0")/skills/swarm/SKILL.md" "$SKILL_DIR/"

echo "✓ Swarm skill installed to $SKILL_DIR"
echo ""
echo "The /swarm skill is now available in Claude Code sessions."
echo "Use it to get guidance on Swarm orchestration workflows."
