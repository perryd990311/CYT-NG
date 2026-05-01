# Agent Work Tracking (BMAD-Inspired)

## Overview
This directory is the agent memory system for CYT-NG. It tracks features, tasks, and completed work so agents maintain context across conversations and sessions.

## Methodology
Inspired by BMAD (Business → Mission → Architecture → Development):

| Layer | Maps To | Tracked In |
|-------|---------|------------|
| **Business** | Epic / Feature goal | GitHub Issue |
| **Mission** | Specific deliverable | Feature `.md` file |
| **Architecture** | Design decisions | `## Architecture` section in feature file |
| **Development** | Implementation steps | `## Tasks` checklist in feature file |

## Directory Structure

```
agent-work/
├── README.md           ← You are here
├── templates/
│   ├── feature.md      ← Template for new features
│   └── task.md         ← Template for standalone tasks
├── backlog/            ← Planned work (not started)
├── active/             ← In-progress work
└── completed/          ← Finished work (knowledge base)
```

## Workflow

### 1. Plan (Backlog)
- Create a GitHub Issue for the feature/epic
- Create a feature `.md` from the template in `backlog/`
- File naming: `NNNN-short-description.md` (NNNN = GitHub issue number)

### 2. Execute (Active)
- Move the file from `backlog/` → `active/`
- Agent checks off tasks as they're completed
- Architecture decisions are recorded inline
- Blockers and pivots are noted

### 3. Complete (Archive)
- All tasks checked, feature verified working
- Move file from `active/` → `completed/`
- Close the GitHub Issue
- Key learnings stay as permanent reference

## Agent Rules

1. **Before starting work**: Check `active/` for in-progress features
2. **Starting new work**: Always create or reference a feature file
3. **During work**: Update task checkboxes and notes in real-time
4. **After work**: Move to `completed/` when done, note any follow-ups
5. **Cross-session**: Read `active/` files to restore context from previous sessions

## Linking to GitHub Issues

Feature files MUST reference their GitHub issue:
```markdown
**GitHub Issue:** #42
**Issue URL:** https://github.com/perryd990311/CYT-NG/issues/42
```

This creates bidirectional traceability:
- Issue → has link to feature file in description or comment
- Feature file → has issue number in header
