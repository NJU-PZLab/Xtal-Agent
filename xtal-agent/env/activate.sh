#!/bin/bash
# xtal-agent environment activation
# Usage: source xtal-agent/env/activate.sh

XTAL_AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export XTAL_AGENT_BASE="${XTAL_AGENT_BASE:-$XTAL_AGENT_DIR}"

# Site-local overrides (machine specific paths; never shipped with releases).
# Provides PHENIX_ENV, CCP4_SETUP and any local PATH entries.
SITE_LOCAL="$XTAL_AGENT_BASE/xtal-agent/env/site.local.sh"
if [ -f "$SITE_LOCAL" ]; then
    . "$SITE_LOCAL"
fi

# Conda environment.
# Prefer the renamed environment; fall back to the legacy name until an
# administrator renames the legacy conda environment.
CONDA_BASE=$(conda info --base 2>/dev/null)
if [ -n "$CONDA_BASE" ] && [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
    . "$CONDA_BASE/etc/profile.d/conda.sh"
    for _xtal_env in xtal-agent crystal-agent; do
        conda activate "$_xtal_env" 2>/dev/null && break
    done
    unset _xtal_env
fi

# Phenix (path supplied by site.local.sh or the caller's environment)
if [ -n "${PHENIX_ENV:-}" ] && [ -f "$PHENIX_ENV" ]; then
    . "$PHENIX_ENV"
fi

# DIALS (bundled with Phenix)
if [ -n "${PHENIX:-}" ] && [ -d "$PHENIX/phenix_bin" ]; then
    export PATH="$PHENIX/phenix_bin:$PATH"
fi

# CCP4 (path supplied by site.local.sh or the caller's environment)
if [ -n "${CCP4_SETUP:-}" ] && [ -f "$CCP4_SETUP" ]; then
    . "$CCP4_SETUP"
    export XTAL_AGENT_CCP4_SETUP="${XTAL_AGENT_CCP4_SETUP:-$CCP4_SETUP}"
fi

# Explicit binary overrides (optional; PATH is still the default contract)
if [ -n "${PHENIX:-}" ] && [ -x "$PHENIX/phenix_bin/phenix.refine" ]; then
    export XTAL_AGENT_PHENIX_BIN="${XTAL_AGENT_PHENIX_BIN:-$PHENIX/phenix_bin/phenix.refine}"
fi
if [ -n "${COOT_BIN:-}" ]; then
    export XTAL_AGENT_COOT_BIN="${XTAL_AGENT_COOT_BIN:-$COOT_BIN}"
fi

# Bundled launchers (xtal-agent, adxv, ...)
export PATH="$XTAL_AGENT_BASE/xtal-agent/env:$PATH"

if command -v xtal-agent &>/dev/null; then
    xtal-agent check-env 2>/dev/null || true
fi
