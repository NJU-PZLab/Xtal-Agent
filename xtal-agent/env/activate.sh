#!/bin/bash
# ============================================================
# Crystal Agent 环境激活脚本
# 用法: source activate.sh
# ============================================================

BASE="${CRYSTAL_AGENT_BASE:-}"
APPS="${CRYSTAL_AGENT_APPS:-${BASE:+$BASE/apps}}"
BIN="${CRYSTAL_AGENT_BIN:-${BASE:+$BASE/bin}}"

# Conda 环境
CONDA_BASE=$(conda info --base 2>/dev/null)
if [ -n "$CONDA_BASE" ] && [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
    source "$CONDA_BASE/etc/profile.d/conda.sh"
    conda activate crystal-agent
fi

# Optional external crystallography environment hooks.
# Public deployments are expected to provide these through environment variables.
PHENIX_ENV="${PHENIX_ENV:-}"
if [ -f "$PHENIX_ENV" ]; then
    source "$PHENIX_ENV"
fi

# CCP4 9
CCP4_SETUP="${CCP4_SETUP:-${APPS:+$APPS/ccp4-9/ccp4-9/bin/ccp4.setup-sh}}"
if [ -f "$CCP4_SETUP" ]; then
    source "$CCP4_SETUP"
fi

# XDS
if [ -n "$BIN" ] && [ -d "$BIN" ]; then
    export PATH="$BIN:$PATH"
fi

# 验证
if command -v crystal-agent &>/dev/null; then
    crystal-agent check-env 2>/dev/null || true
fi
