"""COOT post-refinement module.

Wraps the ``crystallography-coot-refinement`` skill so the orchestrator can
run COOT-based water addition, real-space fitting and rotamer correction as a
normal workflow step instead of asking the LLM to improvise COOT scripts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_STRATEGY = "auto"


class CootNotAvailable(RuntimeError):
    """Raised when COOT (or the bundled COOT skill scripts) is unavailable."""


@dataclass(frozen=True)
class CootResult:
    accepted: bool
    selected_pdb: Path
    selected_mtz: Path
    rfree_before: float | None
    rfree_after: float | None
    rwork_after: float | None
    clashscore: float | None
    rama_outliers: float | None
    rotamer_outliers: float | None
    reason: str
    workdir: Path
    artifacts: list[Path] = field(default_factory=list)


def _repo_root() -> Path:
    # <repo>/xtal-agent/src/xtal_agent/coot_runner.py -> <repo>
    return Path(__file__).resolve().parents[3]


def coot_scripts_dir() -> Path:
    """Locate the bundled COOT skill scripts."""
    env = os.environ.get("XTAL_AGENT_COOT_SCRIPTS")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(_repo_root() / "skills" / "crystallography-coot-refinement" / "scripts")
    # Editable layout fallback: <repo>/xtal-agent/skills/...
    candidates.append(_repo_root() / "xtal-agent" / "skills" / "crystallography-coot-refinement" / "scripts")
    for path in candidates:
        if (path / "run_strategy.py").is_file():
            return path
    raise CootNotAvailable(
        "COOT skill scripts not found. Set XTAL_AGENT_COOT_SCRIPTS to the "
        "crystallography-coot-refinement/scripts directory."
    )


def coot_binary() -> str:
    return os.environ.get("XTAL_AGENT_COOT_BIN", "coot")


def coot_available() -> bool:
    if shutil.which(coot_binary()) is None:
        return False
    try:
        coot_scripts_dir()
    except CootNotAvailable:
        return False
    return True


def _phenix_binary() -> str:
    return os.environ.get("XTAL_AGENT_PHENIX_BIN", "phenix.refine")


def _ccp4_setup() -> str | None:
    env = os.environ.get("XTAL_AGENT_CCP4_SETUP")
    if env:
        return env
    found = shutil.which("ccp4.setup-sh")
    return found


def _resolve_selected_pdb(raw: str | None, workdir: Path, original: Path) -> Path:
    if raw:
        # Some summaries append a human-readable note: "x.pdb (= route ...)"
        cleaned = raw.split(" (", 1)[0].strip()
        path = Path(cleaned)
        if not path.is_absolute():
            path = workdir / path
        if path.is_file():
            return path
    candidates = sorted(
        [p for p in workdir.rglob("*.pdb") if "refined" in p.name.lower()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else original


def run_coot_optimization(
    pdb: str | Path,
    mtz: str | Path,
    workdir: str | Path,
    resolution: float,
    *,
    labels: str = "F,SIGF",
    rfree_label: str = "FreeR_flag",
    strategy: str = DEFAULT_STRATEGY,
    twin_law: str | None = None,
    clash_worse_pct: float = 20.0,
    timeout: int = 6 * 3600,
) -> CootResult:
    """Run the bundled COOT post-refinement strategy.

    The skill itself performs the accept/reject adjudication; this wrapper
    records the outcome and returns the selected model.  If COOT is not
    available the caller should treat the module as skipped.
    """
    pdb = Path(pdb).resolve()
    mtz = Path(mtz).resolve()
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    if not coot_available():
        raise CootNotAvailable(
            f"COOT not available ({coot_binary()!r}); install COOT or set "
            "XTAL_AGENT_COOT_BIN / XTAL_AGENT_COOT_SCRIPTS."
        )

    scripts = coot_scripts_dir()
    config_path = workdir / "config.json"
    config = {
        "workdir": str(workdir / "work"),
        "pdb": str(pdb),
        "mtz": str(mtz),
        "resolution": float(resolution),
        "ccp4_setup": _ccp4_setup() or "",
        "strategy": strategy,
        "coot": coot_binary(),
        "phenix": {
            "labels": labels,
            "rfree_label": rfree_label,
            "phenix_refine": _phenix_binary(),
        },
        "geometry_redline": {"clash_worse_pct": clash_worse_pct},
    }
    if twin_law:
        config["twin_law"] = twin_law
    config_path.write_text(json.dumps(config, indent=2))

    run_log = workdir / "coot_run.log"
    proc = subprocess.run(
        [sys.executable, str(scripts / "run_strategy.py"), "--config", str(config_path)],
        cwd=scripts,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    run_log.write_text(proc.stdout or "")
    if proc.returncode != 0:
        raise RuntimeError(f"COOT strategy failed (exit {proc.returncode}); see {run_log}")

    summary_path = workdir / "work" / "strategy_summary.json"
    if not summary_path.is_file():
        raise RuntimeError(f"COOT strategy did not write {summary_path}")

    summary = json.loads(summary_path.read_text())
    final = summary.get("final") or {}
    start = (
        summary.get("start_rfree")
        or summary.get("start", {}).get("rfree")
        or (summary.get("auto_tournament") or {}).get("baseline", {}).get("rfree")
    )
    rfree = final.get("rfree") if final.get("rfree") is not None else summary.get("rfree")
    rwork = final.get("rwork") if final.get("rwork") is not None else summary.get("rwork")
    geometry = final.get("molprobity") or summary.get("molprobity") or {}

    selected_pdb = _resolve_selected_pdb(final.get("pdb"), workdir / "work", pdb)
    accepted = bool(
        rfree is not None
        and start is not None
        and float(rfree) <= float(start) + 1e-6
    )
    reason = (
        f"selected by COOT strategy ({strategy}); "
        f"Rfree {start} -> {rfree}"
        if accepted
        else f"no Rfree improvement (start {start}, final {rfree}); original model kept"
    )

    artifacts = [config_path, run_log, summary_path, selected_pdb]
    if not accepted:
        selected_pdb = pdb

    return CootResult(
        accepted=accepted,
        selected_pdb=selected_pdb,
        selected_mtz=mtz,
        rfree_before=float(start) if start is not None else None,
        rfree_after=float(rfree) if rfree is not None else None,
        rwork_after=float(rwork) if rwork is not None else None,
        clashscore=geometry.get("clashscore"),
        rama_outliers=geometry.get("rama_outliers_pct"),
        rotamer_outliers=geometry.get("rotamer_outliers_pct"),
        reason=reason,
        workdir=workdir,
        artifacts=artifacts,
    )
