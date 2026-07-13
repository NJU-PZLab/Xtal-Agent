---
name: crystallography-raw-processing
description: Legacy compatibility wrapper. Use only when older docs or user text explicitly names crystallography-raw-processing; otherwise use crystallography-phase1-xds-processing.
---

# Legacy Wrapper: Raw Processing

This skill is kept only for backward compatibility with older references.

For current work, immediately use:

```text
crystallography-phase1-xds-processing
```

Then run:

```bash
source crystal-agent/env/activate.sh
crystal-agent phase-guide phase1
```

Do not continue from this wrapper. The canonical Phase 1 workflow now lives in `skills/crystallography-phase1-xds-processing/SKILL.md` and `crystal-agent phase-guide phase1`.
