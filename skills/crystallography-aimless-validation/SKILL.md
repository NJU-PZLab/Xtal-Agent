---
name: crystallography-aimless-validation
description: Legacy compatibility wrapper. Use only when older docs or user text explicitly names crystallography-aimless-validation; otherwise use crystallography-phase2-aimless-validation.
---

# Legacy Wrapper: AIMLESS Validation

This skill is kept only for backward compatibility with older references.

For current work, immediately use:

```text
crystallography-phase2-aimless-validation
```

Then run:

```bash
source crystal-agent/env/activate.sh
crystal-agent phase-guide phase2
```

Do not continue from this wrapper. The canonical Phase 2 workflow now lives in `skills/crystallography-phase2-aimless-validation/SKILL.md` and `crystal-agent phase-guide phase2`.
