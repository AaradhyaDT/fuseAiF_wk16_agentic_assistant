---
name: conflict-resolution
description: Standard operating procedure for resolving contradictions between design specs and dated release notes.
---

# Conflict Resolution Skill

When multiple sources within the knowledge base provide differing facts, specifications, or numerical values:

1. **Temporal Precedence Invariant**:
   - Dated release notes (`release_notes.md`) and postmortem action items take precedence over initial design documents or tutorial guides.
   - Initial design documents describe initial intentions; release notes describe live operational ground truth.

2. **Reporting Discipline**:
   - Always state the current (superseding) value first.
   - Explicitly document the superseded value and identify where it was found: "Formerly documented as X in [doc:original], superseded by Y as of [doc:release_notes.md]".
   - Include both documents in `citations` so the user can trace the lineage.
