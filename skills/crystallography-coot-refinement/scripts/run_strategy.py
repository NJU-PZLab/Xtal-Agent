# -*- coding: utf-8 -*-
"""run_strategy.py — 精修策略入口（coot 主体 + 同协议收尾 + 两路竞选）。

strategy 字段（config.json，推荐 "auto"）：
  auto                 — 两路并行竞选，唯一变量 = 是否加水：
                           no_waters: coot全残基RSR → 收尾 → rotfix
                           waters:    coot加水迭代(coot-only，molprobity纯打分)
                                      → coot全残基RSR → 收尾 → rotfix
                         裁决：Rfree 最小者胜；clash 超红线顺位；
                         无人优于起点则保底起点模型（已收敛判定）
  waters / no_waters   — 单跑新主干对应路线
  fixed                — 经典五步（旧）：估权重→coot全残基RSR→phenix→rotfix→验证
  waters_refmac        — 旧加水路线（refmac 轮内精修）
  waters_refmac_polish / waters_fixed — 旧路线

架构原则（4Z3U 系列实验确立）：
  1. refmac/phenix 仅用于收尾优化，且与原沉积模型的精修程序一致
     （由 mtz 列名识别：FWT/PHWT→refmac，2FOFCWT→phenix；可用 polish_engine 覆盖）。
     模型本在其原协议谷底，同协议收尾漂移最小。
  2. 加水与实空间精修只用 coot（密度引导，无过拟合能力）；加水轮内评分用
     phenix.molprobity 纯打分（不动坐标，非优化），与裁决同口径。
  3. rotfix 永远放在收尾 refmac/phenix 之后（最后一步）。
  4. 有任何可用建图列即跳过 Phase0 refmac（避免无谓漂移）；仅当 mtz
     完全无图列时才 Phase0（此时收尾引擎视为 refmac）。

裁决口径：phenix.molprobity <pdb> <mtz>（fmodel 管线剔除 F-obs outlier，
与用户基准日志一致）。model_vs_data / refmac 内部 R 不剔 outlier，读数系统性
偏高 ~0.02（协议税），不作裁决；这也是旧 refmac 轮内路线对己收敛模型
"必输"的原因（4Z3U 实测分解：协议税 +0.018，过拟合漂移 +0.015/引擎无关）。

实测结论（4JDH/4MBR/4MLI/4TVS/4TWN/4YPN/4Z3U 七个数据集回归）：
  - 加水参数：σ 扫描 [3.0,2.5,2.0,1.5]，饱和停（新增<20 且 ΔRfree<0.001），回弹回退
  - phenix 默认权重对已收敛模型过拟合（wxc_scale 0.5/0.3 可缓解）
  - 已收敛模型（Phase0/探针轨迹单调上升）任何精修都亏 Rfree → 保底起点

用法：
  python3 run_strategy.py --config config.json
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PHENIX = os.environ.get(
    "XTAL_AGENT_PHENIX_BIN", "phenix.refine"
)
SCRIPT_ADD_WATERS = os.path.join(HERE, "phase_add_waters.py")
SCRIPT_REFINE_ALL = os.path.join(HERE, "phase4_refine_all.py")
SCRIPT_ROTAMERS = os.path.join(HERE, "phase4_rotamers.py")

# refmac 输出 MTZ 的建图列名（Phase 0 / 加水轮 refmac 产物）
REFMAC_MAP_COLS = {"fwt": "FWT", "phwt": "PHWT", "delfwt": "DELFWT", "phdelwt": "PHDELWT"}
# phenix.refine 输出 MTZ 的建图列名（water_engine=phenix 时的轮内产物）
PHENIX_MAP_COLS = {"fwt": "2FOFCWT", "phwt": "PH2FOFCWT",
                   "delfwt": "FOFCWT", "phdelwt": "PHFOFCWT"}


# ---------- 基础执行器 ----------

def run_coot_script(script, params, out_json, workdir, coot_bin="coot", log=None):
    params_path = os.path.join(workdir, "_cootjob_params.json")
    with open(params_path, "w") as f:
        json.dump(params, f, indent=2)
    env = os.environ.copy()
    env["COOTJOB_PARAMS"] = params_path
    env["COOTJOB_OUT_JSON"] = out_json
    env["COOTJOB_SCRIPTS_DIR"] = HERE
    cmd = [coot_bin, "--no-graphics", "-s", script, "--no-guano"]
    proc = subprocess.Popen(cmd, cwd=workdir, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.communicate()[0].decode("utf-8", "replace")
    if log:
        with open(log, "w") as f:
            f.write(out)
    if not os.path.isfile(out_json):
        raise RuntimeError("no result json from %s\n%s" % (script, out[-1500:]))
    with open(out_json) as f:
        res = json.load(f)
    if not res.get("ok"):
        raise RuntimeError("%s failed: %s" % (script, res.get("error")))
    return res


def mtz_column_set(path, ccp4_setup=None):
    """mtz 列名 token 集合；失败返回空集。
    只解析 "Column Labels" 块——整文本分词会把 Column Types 行的单字母
    （F/Q/P...）当列名，导致 _pick_label 误映射（5UBE 教训：FP 被映射成
    类型行的 "F" 而真实列名是 F-obs-filtered）。"""
    try:
        if ccp4_setup and os.path.isfile(ccp4_setup):
            cmd = ["bash", "-c",
                   "source \"%s\" && mtzdump hklin \"%s\" <<'EOF'\nEND\nEOF" % (ccp4_setup, path)]
        else:
            cmd = ["mtzdump", "hklin", path]
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, env=os.environ.copy())
        out = proc.communicate(b"END\n")[0].decode("utf-8", "replace")
        lines = out.splitlines()
        for i, ln in enumerate(lines):
            if "Column Labels" in ln:
                labels = set()
                for t in lines[i + 1:]:
                    t = t.strip()
                    if not t:
                        if labels:
                            break
                        continue
                    if t.startswith("*"):
                        break
                    labels.update(t.split())
                if labels:
                    return labels
                break
        return set(out.split())
    except Exception:
        return set()


def mtz_has_fwt(path, fwt="FWT", phwt="PHWT", ccp4_setup=None):
    cols = mtz_column_set(path, ccp4_setup)
    return fwt in cols and phwt in cols


def detect_refiner_and_map_cols(obs_mtz, ccp4_setup):
    """从 mtz 列名识别沉积模型出身的精修程序与建图列。
    模型处于其原精修协议的局部谷底，收尾用同协议漂移最小（4Z3U 教训）。
    refmac 风格(FWT/PHWT[/FC_ALL_LS]) -> ("refmac", REFMAC_MAP_COLS)
    phenix 风格(2FOFCWT/PH2FOFCWT)    -> ("phenix", PHENIX_MAP_COLS)
    都无 -> (None, None)（需 Phase 0 refmac 建列）"""
    cols = mtz_column_set(obs_mtz, ccp4_setup)
    if "2FOFCWT" in cols and "PH2FOFCWT" in cols:
        return "phenix", dict(PHENIX_MAP_COLS)
    if "FWT" in cols and "PHWT" in cols:
        return "refmac", dict(REFMAC_MAP_COLS)
    return None, None


def parse_refmac_r(out_text):
    """解析 refmac 日志循环表最后一行 (ncyc, Rfact, Rfree)。"""
    best = None
    for line in out_text.splitlines():
        t = line.split()
        if len(t) >= 3 and t[0].isdigit():
            try:
                r, rf = float(t[1]), float(t[2])
            except ValueError:
                continue
            if 0.05 < r < 0.7 and 0.05 < rf < 0.9:
                best = (int(t[0]), r, rf)
    return best


def _pick_label(cols, requested, alternatives):
    """请求的列名不在 mtz 里时按候选表自动映射（5IGO: F/SIGF 而非 FP/SIGFP）。"""
    if requested in cols:
        return requested
    for alt in alternatives:
        if alt in cols:
            return alt
    return requested


def run_refmac(pdb_in, mtz_in, pdb_out, mtz_out, workdir, refmac_cfg,
               ccp4_setup=None, log=None):
    cols = mtz_column_set(mtz_in, ccp4_setup)
    fobs = _pick_label(cols, refmac_cfg.get("fobs", "FP"),
                       ["F", "F-obs", "FOBS", "F-obs-filtered", "FP"])
    sigfobs = _pick_label(cols, refmac_cfg.get("sigfobs", "SIGFP"),
                          ["SIGF", "SIGF-obs", "SIGFOBS", "SIGF-obs-filtered", "SIGFP"])
    rfree = _pick_label(cols, refmac_cfg.get("rfree", "FreeR_flag"),
                        ["FreeR_flag", "R-free-flags", "FREE", "FreeRflag"])
    ncyc = refmac_cfg.get("n_cycles", "10")
    extra = refmac_cfg.get("extra_keywords", "")
    stdin = "LABIN FP=%s SIGFP=%s FREE=%s\nNCYC %s\n%s\nEND\n" % (
        fobs, sigfobs, rfree, ncyc, extra)
    if ccp4_setup and os.path.isfile(ccp4_setup):
        cmd = ["bash", "-c",
               "source \"%s\" && refmac5 XYZIN \"%s\" XYZOUT \"%s\" HKLIN \"%s\" HKLOUT \"%s\"" % (
                   ccp4_setup, pdb_in, pdb_out, mtz_in, mtz_out)]
    else:
        cmd = ["refmac5", "XYZIN", pdb_in, "XYZOUT", pdb_out,
               "HKLIN", mtz_in, "HKLOUT", mtz_out]
    proc = subprocess.Popen(cmd, cwd=workdir, env=os.environ.copy(),
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.communicate(stdin.encode())[0].decode("utf-8", "replace")
    if log:
        with open(log, "w") as f:
            f.write(out)
    if proc.returncode != 0 or not os.path.isfile(mtz_out):
        raise RuntimeError("refmac5 failed (rc=%s)" % proc.returncode)
    r = parse_refmac_r(out)
    return {"pdb_out": pdb_out, "mtz_out": mtz_out,
            "ncyc": r[0] if r else None,
            "rwork": r[1] if r else None,
            "rfree": r[2] if r else None}


def run_phenix(pdb, mtz, workdir, prefix, phenix_cfg, log=None, wxc_scale=None):
    phenix_bin = phenix_cfg.get("phenix_refine", DEFAULT_PHENIX)
    cmd = [
        phenix_bin, pdb, mtz,
        "xray_data.labels=%s" % phenix_cfg.get("labels", "F,SIGF"),
        "xray_data.r_free_flags.label=%s" % phenix_cfg.get("rfree_label", "FreeR_flag"),
        "main.number_of_macro_cycles=%s" % phenix_cfg.get("n_cycles", "3"),
        "refine.strategy=%s" % phenix_cfg.get("strategy", "*individual_sites individual_adp"),
        "output.prefix=%s" % prefix,
        "overwrite=True",   # 管线化运行允许覆盖同 workdir 旧输出
    ]
    if wxc_scale is not None:
        cmd.append("wxc_scale=%s" % wxc_scale)
    if phenix_cfg.get("twin_law"):   # 缺面体孪晶（如 5L2E: -h,-k,l）
        cmd.append("xray_data.twin_law=%s" % phenix_cfg["twin_law"])
    for cif in phenix_cfg.get("cif_files", []):   # 配体自定义约束（如 UO1）
        cmd.append(os.path.abspath(cif))
    proc = subprocess.Popen(cmd, cwd=workdir,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.communicate()[0].decode("utf-8", "replace")
    if log:
        with open(log, "w") as f:
            f.write(out)
    m = re.search(r"Final R-work = ([\d.]+), R-free = ([\d.]+)", out)
    if not m:
        raise RuntimeError("phenix.refine no final R: %s" % out[-800:])
    return {
        "rwork": float(m.group(1)), "rfree": float(m.group(2)),
        "pdb": os.path.join(workdir, prefix + "_001.pdb"),
        "mtz": os.path.join(workdir, prefix + "_001.mtz"),
    }


def run_rotalyze(pdb, workdir, phenix_cfg, log=None):
    """跑 phenix.rotalyze，返回问题清单 json 路径（phase4_rotamers 的 problem.rotamer 格式）。"""
    phenix_bin = phenix_cfg.get("phenix_refine", DEFAULT_PHENIX)
    rotalyze_bin = phenix_bin.replace("phenix.refine", "phenix.rotalyze")
    proc = subprocess.Popen([rotalyze_bin, pdb], cwd=workdir,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.communicate()[0].decode("utf-8", "replace")
    if log:
        with open(log, "w") as f:
            f.write(out)
    items = []
    for line in out.splitlines():
        if ":OUTLIER" in line:
            m = re.match(r"\s*(\S+)\s+(\d+)\s+(\w+):", line)
            if m:
                items.append({"chain": m.group(1), "resno": int(m.group(2)),
                              "ins_code": "", "res_type": m.group(3)})
    pl_path = os.path.join(workdir, "rotamer_outliers.json")
    with open(pl_path, "w") as f:
        json.dump({"problem": {"rotamer": items}}, f, indent=2)
    return pl_path, len(items)


def _grab(pat, text):
    m = re.search(pat, text)
    return float(m.group(1)) if m else None


def _twin_r_factors(pdb, mtz, workdir, phenix_cfg, log=None):
    """twin-aware R 值：phenix.model_vs_data + twin_law（5L2E 缺面体孪晶教训：
    molprobity 不应用 twin law，R 虚高 0.4263 vs 真实 0.3286）。"""
    mvd_bin = phenix_cfg.get("phenix_refine", DEFAULT_PHENIX).replace(
        "phenix.refine", "phenix.model_vs_data")
    cmd = [mvd_bin, pdb, mtz, "twin_law=%s" % phenix_cfg["twin_law"]]
    proc = subprocess.Popen(cmd, cwd=workdir,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.communicate()[0].decode("utf-8", "replace")
    if log:
        with open(log, "a") as f:
            f.write("\n===== model_vs_data twin_law=%s (R values authoritative) =====\n%s\n"
                    % (phenix_cfg["twin_law"], out[-3000:]))
    res = {}
    m1 = re.search(r"r_work:\s*([\d.]+)", out)
    m2 = re.search(r"r_free:\s*([\d.]+)", out)
    if m1 and m2:
        res["rwork"] = float(m1.group(1))
        res["rfree"] = float(m2.group(1))
    return res


def run_molprobity(pdb, workdir, phenix_cfg, mtz=None, log=None):
    """phenix.molprobity 几何验证；给 mtz 时同时解析 r_work/r_free（裁决口径）。
    twin_law 存在时 R 值改由 model_vs_data（twin-aware）裁决，几何仍取 molprobity。"""
    phenix_bin = phenix_cfg.get("phenix_refine", DEFAULT_PHENIX)
    mp_bin = phenix_bin.replace("phenix.refine", "phenix.molprobity")
    cmd = [mp_bin, pdb] + ([mtz] if mtz else [])
    proc = subprocess.Popen(cmd, cwd=workdir,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.communicate()[0].decode("utf-8", "replace")
    if log:
        with open(log, "w") as f:
            f.write(out)
    res = {
        "rama_outliers_pct": _grab(r"Ramachandran outliers\s*=\s*([\d.]+)", out),
        "rotamer_outliers_pct": _grab(r"Rotamer outliers\s*=\s*([\d.]+)", out),
        "clashscore": _grab(r"Clashscore\s*=\s*([\d.]+)", out),
        "cbeta_deviations": _grab(r"C-beta deviations\s*=\s*([\d.]+)", out),
    }
    m = re.search(r"r_work=\s*([\d.]+)\s*r_free=\s*([\d.]+)", out)
    if m:
        res["rwork"] = float(m.group(1))
        res["rfree"] = float(m.group(2))
    if mtz and phenix_cfg.get("twin_law"):
        res.update(_twin_r_factors(pdb, mtz, workdir, phenix_cfg, log=log))
    return res


# ---------- 公共步骤 ----------

def derive_refmac_cfg(cfg):
    """refmac 列名：显式 refmac 配置优先，否则从 phenix labels 推导。"""
    refmac_cfg = dict(cfg.get("refmac", {}))
    if "fobs" not in refmac_cfg and cfg.get("phenix", {}).get("labels"):
        labels = cfg["phenix"]["labels"].split(",")
        if len(labels) >= 2:
            refmac_cfg.setdefault("fobs", labels[0].strip())
            refmac_cfg.setdefault("sigfobs", labels[1].strip())
    if "rfree" not in refmac_cfg and cfg.get("phenix", {}).get("rfree_label"):
        refmac_cfg.setdefault("rfree", cfg["phenix"]["rfree_label"])
    return refmac_cfg


def ensure_phase0(cfg, workdir, pdb, obs_mtz, ccp4_setup, coot_bin=None):
    """确定建图来源与原精修程序。返回 (pdb, map_mtz, map_cols, phase0_info, engine)。

    有任何可用建图列（phenix 或 refmac 风格）则跳过 Phase 0 直接用原图——
    避免 refmac Phase 0 对已收敛模型的无谓漂移（4Z3U：+0.0145）；
    仅当 mtz 完全无建图列时才跑 Phase 0 refmac（此时 engine 视为 refmac）。
    显式 cfg.mtz_columns 优先，engine 由 fwt 列名风格推断。"""
    explicit = cfg.get("mtz_columns")
    if explicit:
        eng = "phenix" if "2FOFCWT" in explicit.get("fwt", "") else "refmac"
        return pdb, obs_mtz, explicit, None, eng
    engine, cols = detect_refiner_and_map_cols(obs_mtz, ccp4_setup)
    if engine:
        return pdb, obs_mtz, cols, None, engine
    rm = run_refmac(
        pdb, obs_mtz,
        os.path.join(workdir, "phase0_refmac.pdb"),
        os.path.join(workdir, "phase0_refmac.mtz"),
        workdir, derive_refmac_cfg(cfg), ccp4_setup,
        log=os.path.join(workdir, "refmac_phase0.log"))
    return rm["pdb_out"], rm["mtz_out"], dict(REFMAC_MAP_COLS), rm, "refmac"


def coot_add_waters(pdb, map_mtz, map_cols, sigma, out_pdb, workdir, coot_bin,
                    log=None, water_dist_min=None, water_dist_max=None):
    params = dict(pdb=pdb, mtz=map_mtz, mtz_columns=map_cols,
                  sigma=float(sigma), out_pdb=out_pdb)
    if water_dist_min is not None and water_dist_max is not None:
        params["water_dist_min"] = float(water_dist_min)
        params["water_dist_max"] = float(water_dist_max)
    return run_coot_script(SCRIPT_ADD_WATERS, params,
                           os.path.join(workdir, "add_waters_result.json"),
                           workdir, coot_bin, log=log)


def run_water_rounds(pdb0, map_mtz, map_cols, obs_mtz, workdir, cfg,
                     ccp4_setup, coot_bin):
    """coot 加水迭代：轮1 σ 扫描（含无加水对照），轮2+ 定点σ迭代至饱和/回弹。

    轮内排序用 refmac 内部 Rfree（同协议可比）。
    返回 dict: pdb/mtz（最终模型与相位图）, sigma_used, history, waters_total
    """
    wcfg = cfg.get("waters", {})
    sigmas = [float(s) for s in wcfg.get("sigma", [3.0, 2.5, 2.0, 1.5])]
    max_rounds = int(wcfg.get("max_rounds", 3))
    min_new = int(wcfg.get("saturation_min_new", 20))
    min_gain = float(wcfg.get("saturation_min_gain", 0.001))
    revert = bool(wcfg.get("revert_on_bounce", True))
    refmac_cfg = derive_refmac_cfg(cfg)
    # 轮内精修引擎：refmac（默认，快/紧几何）或 phenix（内部 Rfree 与裁决同协议，
    # 无 +0.02 协议税，但慢且默认权重对已收敛模型有过拟合风险）
    engine = str(wcfg.get("engine", "refmac")).lower()
    phenix_cfg = cfg.get("phenix", {})
    map_cols_iter = REFMAC_MAP_COLS if engine == "refmac" else PHENIX_MAP_COLS
    history = []

    def refine_one(pdb_in, tag):
        if engine == "phenix":
            wd = os.path.join(workdir, "refine_%s" % tag)   # 独立子目录防并行冲突
            if not os.path.isdir(wd):
                os.makedirs(wd)
            r = run_phenix(pdb_in, obs_mtz, wd, tag, phenix_cfg,
                           log=os.path.join(wd, "phenix.log"))
            return {"rfree": r["rfree"], "rwork": r["rwork"],
                    "pdb_out": r["pdb"], "mtz_out": r["mtz"]}
        return run_refmac(pdb_in, obs_mtz,
                          os.path.join(workdir, "%s_refmac.pdb" % tag),
                          os.path.join(workdir, "%s_refmac.mtz" % tag),
                          workdir, refmac_cfg, ccp4_setup,
                          log=os.path.join(workdir, "%s_refmac.log" % tag))

    # ---- 轮 1: σ 扫描 + 无加水对照（并行） ----
    round1 = os.path.join(workdir, "round1")
    if not os.path.isdir(round1):
        os.makedirs(round1)
    jobs = [("ctrl", None, pdb0)]
    for s in sigmas:
        sd = os.path.join(round1, "sig%s" % s)
        if not os.path.isdir(sd):
            os.makedirs(sd)
        wa = coot_add_waters(pdb0, map_mtz, map_cols, s,
                             os.path.join(sd, "waters.pdb"), sd, coot_bin,
                             log=os.path.join(sd, "add_waters.log"))
        jobs.append(("sig%s" % s, s, wa["out_pdb"]))
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        rms = list(ex.map(lambda j: refine_one(j[2], j[0]), jobs))
    cands = []
    for (tag, s, _in), rm in zip(jobs, rms):
        n_w = None
        if s is not None:
            with open(os.path.join(round1, "sig%s" % s, "add_waters_result.json")) as f:
                n_w = json.load(f).get("waters_after")
        cands.append({"tag": tag, "sigma": s, "rfree": rm["rfree"],
                      "pdb": rm["pdb_out"], "mtz": rm["mtz_out"],
                      "waters": n_w})
        history.append(dict(cands[-1], round=1))
    cands = [c for c in cands if c["rfree"] is not None]
    best = min(cands, key=lambda c: c["rfree"])
    sigma_used = best["sigma"] if best["sigma"] is not None else min(sigmas)
    prev = best

    # ---- 轮 2+: 定点 σ 迭代，饱和停/回弹退 ----
    for rnd in range(2, max_rounds + 1):
        rd = os.path.join(workdir, "round%d" % rnd)
        if not os.path.isdir(rd):
            os.makedirs(rd)
        wa = coot_add_waters(prev["pdb"], prev["mtz"], map_cols_iter,
                             sigma_used,
                             os.path.join(rd, "waters.pdb"), rd, coot_bin,
                             log=os.path.join(rd, "add_waters.log"))
        n_added = wa.get("waters_added", 0)
        rm = refine_one(wa["out_pdb"], "round%d" % rnd)
        cur = {"tag": "round%d" % rnd, "sigma": sigma_used,
               "rfree": rm["rfree"], "pdb": rm["pdb_out"],
               "mtz": rm["mtz_out"], "waters": wa.get("waters_after"),
               "waters_added": n_added}
        history.append(dict(cur, round=rnd))
        gain = (prev["rfree"] - rm["rfree"]) if rm["rfree"] is not None else 0.0
        if rm["rfree"] is None or (n_added < min_new and gain < min_gain):
            if rm["rfree"] is not None and rm["rfree"] < prev["rfree"]:
                prev = cur   # 未饱和且仍在改善：接受
            break
        if rm["rfree"] > prev["rfree"] and revert:
            break            # 回弹：保留上一轮
        prev = cur

    return {"pdb": prev["pdb"], "mtz": prev["mtz"], "sigma_used": sigma_used,
            "history": history, "waters_total": prev.get("waters"),
            "rfree_refmac": prev["rfree"],   # 键名向后兼容；engine=phenix 时为 phenix 内部 Rfree
            "engine": engine, "map_cols": map_cols_iter}


def run_water_rounds_coot(pdb0, map_mtz, map_cols, obs_mtz, workdir, cfg,
                          coot_bin):
    """coot-only 加水迭代（新主干用）：轮内不做任何倒易空间精修。

    σ 扫描与轮次评分统一用 phenix.molprobity(fmodel) 纯打分——不动坐标、
    与终验同口径。轮1 σ 扫描+无加水对照（并行），轮2+ 定点 σ 迭代至
    饱和/回弹。相位图始终用初始图（coot find_waters 自动避开已有水）。
    返回 dict: pdb（最佳加水模型）, sigma_used, history, waters_total。
    """
    wcfg = cfg.get("waters", {})
    sigmas = [float(s) for s in wcfg.get("sigma", [3.0, 2.5, 2.0, 1.5])]
    max_rounds = int(wcfg.get("max_rounds", 3))
    min_new = int(wcfg.get("saturation_min_new", 20))
    min_gain = float(wcfg.get("saturation_min_gain", 0.001))
    revert = bool(wcfg.get("revert_on_bounce", True))
    phenix_cfg = cfg.get("phenix", {})
    history = []

    def score_one(pdb_in, tag):
        wd = os.path.join(workdir, "score_%s" % tag)
        if not os.path.isdir(wd):
            os.makedirs(wd)
        ev = run_molprobity(pdb_in, wd, phenix_cfg, mtz=obs_mtz,
                            log=os.path.join(wd, "molprobity.log"))
        return {"rfree": ev.get("rfree"), "pdb_out": pdb_in}

    # ---- 轮 1: σ 扫描 + 无加水对照（并行打分） ----
    round1 = os.path.join(workdir, "round1")
    if not os.path.isdir(round1):
        os.makedirs(round1)
    jobs = [("ctrl", None, pdb0)]
    for s in sigmas:
        sd = os.path.join(round1, "sig%s" % s)
        if not os.path.isdir(sd):
            os.makedirs(sd)
        wa = coot_add_waters(pdb0, map_mtz, map_cols, s,
                             os.path.join(sd, "waters.pdb"), sd, coot_bin,
                             log=os.path.join(sd, "add_waters.log"),
                             water_dist_min=wcfg.get("water_dist_min"),
                             water_dist_max=wcfg.get("water_dist_max"))
        jobs.append(("sig%s" % s, s, wa["out_pdb"]))
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        scs = list(ex.map(lambda j: score_one(j[2], j[0]), jobs))
    cands = []
    for (tag, s, _in), sc in zip(jobs, scs):
        n_w = None
        if s is not None:
            with open(os.path.join(round1, "sig%s" % s,
                                   "add_waters_result.json")) as f:
                n_w = json.load(f).get("waters_after")
        cands.append({"tag": tag, "sigma": s, "rfree": sc["rfree"],
                      "pdb": sc["pdb_out"], "waters": n_w})
        history.append(dict(cands[-1], round=1))
    cands = [c for c in cands if c["rfree"] is not None]
    best = min(cands, key=lambda c: c["rfree"])
    sigma_used = best["sigma"] if best["sigma"] is not None else min(sigmas)
    prev = best

    # ---- 轮 2+: 定点 σ 迭代，饱和停/回弹退 ----
    for rnd in range(2, max_rounds + 1):
        rd = os.path.join(workdir, "round%d" % rnd)
        if not os.path.isdir(rd):
            os.makedirs(rd)
        wa = coot_add_waters(prev["pdb"], map_mtz, map_cols, sigma_used,
                             os.path.join(rd, "waters.pdb"), rd, coot_bin,
                             log=os.path.join(rd, "add_waters.log"),
                             water_dist_min=wcfg.get("water_dist_min"),
                             water_dist_max=wcfg.get("water_dist_max"))
        n_added = wa.get("waters_added", 0)
        sc = score_one(wa["out_pdb"], "round%d" % rnd)
        cur = {"tag": "round%d" % rnd, "sigma": sigma_used,
               "rfree": sc["rfree"], "pdb": sc["pdb_out"],
               "waters": wa.get("waters_after"), "waters_added": n_added}
        history.append(dict(cur, round=rnd))
        gain = (prev["rfree"] - sc["rfree"]) if sc["rfree"] is not None else 0.0
        if sc["rfree"] is None or (n_added < min_new and gain < min_gain):
            if sc["rfree"] is not None and sc["rfree"] < prev["rfree"]:
                prev = cur   # 未饱和且仍在改善：接受
            break
        if sc["rfree"] > prev["rfree"] and revert:
            break            # 回弹：保留上一轮
        prev = cur

    return {"pdb": prev["pdb"], "sigma_used": sigma_used,
            "history": history, "waters_total": prev.get("waters"),
            "rfree_scored": prev["rfree"]}


def run_rotfix(pdb, mtz, map_cols, workdir, cfg, coot_bin, log_prefix="rotfix"):
    """rotalyze 出清单 + phase4_rotamers 修复。返回 (final_pdb, rot_info or None)。"""
    phenix_cfg = cfg.get("phenix", {})
    pl_path, n_out = run_rotalyze(pdb, workdir, phenix_cfg,
                                  log=os.path.join(workdir, "%s_rotalyze.log" % log_prefix))
    if n_out == 0:
        return pdb, {"outliers_found": 0, "n_fixed": 0, "density_supported": []}
    p_rot = dict(
        pdb=pdb, mtz=mtz,
        dict_cifs=[os.path.abspath(p) for p in cfg.get("dict_cifs", [])],
        mtz_columns=map_cols,
        max_density_to_fix=float(cfg.get("max_density_to_fix", 0.5)),
        min_canonical_prob=float(cfg.get("min_canonical_prob", 5.0)),
        problem_list_json=pl_path,
        out_pdb=os.path.join(workdir, "%s_rotamers_fixed.pdb" % log_prefix),
    )
    r_rot = run_coot_script(SCRIPT_ROTAMERS, p_rot,
                            os.path.join(workdir, "%s_rotamers_result.json" % log_prefix),
                            workdir, coot_bin,
                            log=os.path.join(workdir, "%s_rotamers.log" % log_prefix))
    return r_rot["out_pdb"], r_rot


# ---------- 新主干：两路竞选（唯一变量 = 是否加水） ----------

def route_coot_core(cfg, workdir, ctx, with_waters):
    """加水(可选, coot-only) → coot 全残基 RSR → 收尾(refmac|phenix 按原模型出身)
    → rotfix(永远最后)。

    收尾引擎与原模型精修程序一致（ctx["engine"]，由 mtz 列名识别）：
    模型本就在其原协议谷底，同协议收尾漂移最小。
    """
    coot_bin = cfg.get("coot", "coot")
    pdb_cur, map_mtz, map_cols = ctx["pdb"], ctx["map_mtz"], ctx["map_cols"]
    wr = None
    if with_waters:
        wr = run_water_rounds_coot(pdb_cur, map_mtz, map_cols, ctx["obs_mtz"],
                                   os.path.join(workdir, "waters"),
                                   cfg, coot_bin)
        pdb_cur = wr["pdb"]
    params = dict(
        pdb=pdb_cur, mtz=map_mtz,
        resolution=float(cfg.get("resolution", 2.0)),
        dict_cifs=[os.path.abspath(p) for p in cfg.get("dict_cifs", [])],
        mtz_columns=map_cols,
        refine_weight=cfg.get("refine_weight", "auto"),
        zone_size=int(cfg.get("zone_size", 5)),
        out_pdb=os.path.join(workdir, "refine_all.pdb"),
    )
    r_all = run_coot_script(SCRIPT_REFINE_ALL, params,
                            os.path.join(workdir, "refine_all_result.json"),
                            workdir, coot_bin,
                            log=os.path.join(workdir, "refine_all.log"))
    engine = ctx.get("engine") or "refmac"
    if engine == "phenix":
        r_fin = run_phenix(r_all["out_pdb"], ctx["obs_mtz"], workdir, "final",
                           cfg.get("phenix", {}),
                           log=os.path.join(workdir, "phenix_final.log"))
        fin_pdb, fin_mtz, fin_cols = r_fin["pdb"], r_fin["mtz"], ctx["map_cols_phenix"]
    else:
        r_fin = run_refmac(r_all["out_pdb"], ctx["obs_mtz"],
                           os.path.join(workdir, "final_refmac.pdb"),
                           os.path.join(workdir, "final_refmac.mtz"),
                           workdir, derive_refmac_cfg(cfg), ctx["ccp4_setup"],
                           log=os.path.join(workdir, "refmac_final.log"))
        fin_pdb, fin_mtz, fin_cols = (r_fin["pdb_out"], r_fin["mtz_out"],
                                      dict(REFMAC_MAP_COLS))
    final_pdb, r_rot = fin_pdb, None
    if cfg.get("fix_rotamers", True):
        final_pdb, r_rot = run_rotfix(fin_pdb, fin_mtz, fin_cols,
                                      workdir, cfg, coot_bin)
    info = {"polish_engine": engine,
            "weight_used": r_all.get("weight_used"),
            "residues_moved": r_all.get("residues_moved"),
            "polish_rwork": r_fin.get("rwork"), "polish_rfree": r_fin.get("rfree"),
            "rotamer_outliers_found": (r_rot or {}).get("outliers_found"),
            "rotamer_fixed": (r_rot or {}).get("n_fixed"),
            "rotamer_density_supported_kept": (r_rot or {}).get("density_supported")}
    if wr:
        info.update({"sigma_used": wr["sigma_used"],
                     "waters_total": wr["waters_total"],
                     "rfree_after_waters": wr["rfree_scored"],
                     "water_history": wr["history"]})
    return {"pdb": final_pdb, "mtz": fin_mtz, "info": info}


def route_waters(cfg, workdir, ctx):
    """新主干·加水路。"""
    return route_coot_core(cfg, workdir, ctx, with_waters=True)


def route_no_waters(cfg, workdir, ctx):
    """新主干·不加水对照路。"""
    return route_coot_core(cfg, workdir, ctx, with_waters=False)


# ---------- 三条命名路线 ----------

def route_fixed(cfg, workdir, ctx):
    """经典五步：估权重→coot全残基RSR→phenix→rotfix→验证。"""
    coot_bin = cfg.get("coot", "coot")
    params = dict(
        pdb=ctx["pdb"], mtz=ctx["map_mtz"],
        resolution=float(cfg.get("resolution", 2.0)),
        dict_cifs=[os.path.abspath(p) for p in cfg.get("dict_cifs", [])],
        mtz_columns=ctx["map_cols"],
        refine_weight=cfg.get("refine_weight", "auto"),
        zone_size=int(cfg.get("zone_size", 5)),
        out_pdb=os.path.join(workdir, "refine_all.pdb"),
    )
    r_all = run_coot_script(SCRIPT_REFINE_ALL, params,
                            os.path.join(workdir, "refine_all_result.json"),
                            workdir, coot_bin,
                            log=os.path.join(workdir, "refine_all.log"))
    r_ph = run_phenix(r_all["out_pdb"], ctx["obs_mtz"], workdir, "final",
                      cfg.get("phenix", {}), log=os.path.join(workdir, "phenix.log"))
    final_pdb, r_rot = r_ph["pdb"], None
    if cfg.get("fix_rotamers", True):
        final_pdb, r_rot = run_rotfix(r_ph["pdb"], r_ph["mtz"],
                                      ctx["map_cols_phenix"], workdir, cfg, coot_bin)
    return {"pdb": final_pdb, "mtz": r_ph["mtz"],
            "info": {"weight_used": r_all.get("weight_used"),
                     "residues_moved": r_all.get("residues_moved"),
                     "phenix_rwork": r_ph["rwork"], "phenix_rfree": r_ph["rfree"],
                     "rotamer_outliers_found": (r_rot or {}).get("outliers_found"),
                     "rotamer_fixed": (r_rot or {}).get("n_fixed"),
                     "rotamer_density_supported_kept": (r_rot or {}).get("density_supported")}}


def route_waters_refmac(cfg, workdir, ctx):
    """Phase0(按需)→加水迭代→refmac→rotfix。"""
    coot_bin = cfg.get("coot", "coot")
    wr = run_water_rounds(ctx["pdb"], ctx["map_mtz"], ctx["map_cols"],
                          ctx["obs_mtz"], workdir, cfg,
                          ctx["ccp4_setup"], coot_bin)
    final_pdb, r_rot = wr["pdb"], None
    if cfg.get("fix_rotamers", True):
        final_pdb, r_rot = run_rotfix(wr["pdb"], wr["mtz"],
                                      wr.get("map_cols", REFMAC_MAP_COLS),
                                      workdir, cfg, coot_bin)
    return {"pdb": final_pdb, "mtz": wr["mtz"],
            "info": {"sigma_used": wr["sigma_used"],
                     "waters_total": wr["waters_total"],
                     "rfree_refmac": wr["rfree_refmac"],
                     "water_history": wr["history"],
                     "rotamer_outliers_found": (r_rot or {}).get("outliers_found"),
                     "rotamer_fixed": (r_rot or {}).get("n_fixed"),
                     "rotamer_density_supported_kept": (r_rot or {}).get("density_supported")}}


def route_waters_refmac_polish(cfg, workdir, ctx):
    """waters_refmac + phenix 紧权重几何收尾（wxc_scale 扫描，裁决口径选优）→ rotfix。"""
    coot_bin = cfg.get("coot", "coot")
    wr = run_water_rounds(ctx["pdb"], ctx["map_mtz"], ctx["map_cols"],
                          ctx["obs_mtz"], os.path.join(workdir, "waters"), cfg,
                          ctx["ccp4_setup"], coot_bin)
    scales = cfg.get("phenix_polish", {}).get("wxc_scale", [0.5, 0.3])
    cands = []
    for w in scales:
        wd = os.path.join(workdir, "polish_w%s" % w)
        if not os.path.isdir(wd):
            os.makedirs(wd)
        r_ph = run_phenix(wr["pdb"], ctx["obs_mtz"], wd, "polish",
                          cfg.get("phenix", {}),
                          log=os.path.join(wd, "phenix.log"), wxc_scale=w)
        ev = run_molprobity(r_ph["pdb"], wd, cfg.get("phenix", {}),
                            mtz=ctx["obs_mtz"],
                            log=os.path.join(wd, "molprobity.log"))
        cands.append({"wxc_scale": w, "pdb": r_ph["pdb"], "mtz": r_ph["mtz"],
                      "rfree": ev.get("rfree"), "eval": ev})
    cands = [c for c in cands if c["rfree"] is not None]
    if not cands:   # polish 全失败则退回 waters 模型
        best = {"pdb": wr["pdb"], "mtz": wr["mtz"], "wxc_scale": None}
    else:
        best = min(cands, key=lambda c: c["rfree"])
    final_pdb, r_rot = best["pdb"], None
    if cfg.get("fix_rotamers", True):
        cols = ctx["map_cols_phenix"] if best.get("wxc_scale") else wr.get("map_cols", REFMAC_MAP_COLS)
        final_pdb, r_rot = run_rotfix(best["pdb"], best["mtz"], cols,
                                      workdir, cfg, coot_bin)
    return {"pdb": final_pdb, "mtz": best["mtz"],
            "info": {"sigma_used": wr["sigma_used"],
                     "waters_total": wr["waters_total"],
                     "water_history": wr["history"],
                     "polish_wxc_scale": best.get("wxc_scale"),
                     "polish_candidates": [{"wxc_scale": c["wxc_scale"],
                                            "rfree": c["rfree"]} for c in cands],
                     "rotamer_outliers_found": (r_rot or {}).get("outliers_found"),
                     "rotamer_fixed": (r_rot or {}).get("n_fixed"),
                     "rotamer_density_supported_kept": (r_rot or {}).get("density_supported")}}


def route_waters_fixed(cfg, workdir, ctx):
    """加水迭代 → 经典五步主体（coot全残基RSR→phenix默认）→ rotfix。"""
    coot_bin = cfg.get("coot", "coot")
    wr = run_water_rounds(ctx["pdb"], ctx["map_mtz"], ctx["map_cols"],
                          ctx["obs_mtz"], os.path.join(workdir, "waters"), cfg,
                          ctx["ccp4_setup"], coot_bin)
    params = dict(
        pdb=wr["pdb"], mtz=wr["mtz"],
        resolution=float(cfg.get("resolution", 2.0)),
        dict_cifs=[os.path.abspath(p) for p in cfg.get("dict_cifs", [])],
        mtz_columns=wr.get("map_cols", REFMAC_MAP_COLS),
        refine_weight=cfg.get("refine_weight", "auto"),
        zone_size=int(cfg.get("zone_size", 5)),
        out_pdb=os.path.join(workdir, "refine_all.pdb"),
    )
    r_all = run_coot_script(SCRIPT_REFINE_ALL, params,
                            os.path.join(workdir, "refine_all_result.json"),
                            workdir, coot_bin,
                            log=os.path.join(workdir, "refine_all.log"))
    r_ph = run_phenix(r_all["out_pdb"], ctx["obs_mtz"], workdir, "final",
                      cfg.get("phenix", {}), log=os.path.join(workdir, "phenix.log"))
    final_pdb, r_rot = r_ph["pdb"], None
    if cfg.get("fix_rotamers", True):
        final_pdb, r_rot = run_rotfix(r_ph["pdb"], r_ph["mtz"],
                                      ctx["map_cols_phenix"], workdir, cfg, coot_bin)
    return {"pdb": final_pdb, "mtz": r_ph["mtz"],
            "info": {"sigma_used": wr["sigma_used"],
                     "waters_total": wr["waters_total"],
                     "water_history": wr["history"],
                     "weight_used": r_all.get("weight_used"),
                     "phenix_rwork": r_ph["rwork"], "phenix_rfree": r_ph["rfree"],
                     "rotamer_outliers_found": (r_rot or {}).get("outliers_found"),
                     "rotamer_fixed": (r_rot or {}).get("n_fixed"),
                     "rotamer_density_supported_kept": (r_rot or {}).get("density_supported")}}


ROUTES = {"fixed": route_fixed,
          "waters_refmac": route_waters_refmac,
          "waters_refmac_polish": route_waters_refmac_polish,
          "waters_fixed": route_waters_fixed,
          "waters": route_waters,
          "no_waters": route_no_waters}
AUTO_ROUTES = ["no_waters", "waters"]   # 新竞选：唯一变量 = 是否加水


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    workdir = os.path.abspath(cfg.get("workdir", "strategy_job"))
    if not os.path.isdir(workdir):
        os.makedirs(workdir)
    coot_bin = cfg.get("coot", "coot")
    ccp4_setup = cfg.get("ccp4_setup")
    phenix_cfg = dict(cfg.get("phenix", {}))
    if cfg.get("twin_law"):   # 孪晶数据：twin_law 注入所有 phenix 调用与裁决打分
        phenix_cfg["twin_law"] = cfg["twin_law"]
        cfg["phenix"] = phenix_cfg

    pdb0 = os.path.abspath(cfg["pdb"])
    obs_mtz = os.path.abspath(cfg["mtz"])           # 观测 MTZ（phenix/裁决用）
    strategy = cfg.get("strategy", "fixed")

    # 起点基线（裁决口径；红线与 Δ 报告共用）
    baseline = run_molprobity(pdb0, workdir, phenix_cfg, mtz=obs_mtz,
                              log=os.path.join(workdir, "molprobity_start.log"))
    print("baseline: rwork=%s rfree=%s clash=%s" % (
        baseline.get("rwork"), baseline.get("rfree"), baseline.get("clashscore")))

    # 建图来源 + 原精修程序识别（有可用图列则跳过 Phase 0）
    pdb_s, map_mtz, map_cols, phase0, engine0 = ensure_phase0(
        cfg, workdir, pdb0, obs_mtz, ccp4_setup)
    engine = cfg.get("polish_engine") or engine0   # 收尾引擎，可显式覆盖
    print("map source: %s | original refiner: %s -> polish engine: %s" % (
        "Phase0(refmac)" if phase0 else "deposited mtz columns",
        engine0, engine))
    ctx = {"pdb": pdb_s, "map_mtz": map_mtz, "map_cols": map_cols,
           "obs_mtz": obs_mtz, "ccp4_setup": ccp4_setup, "engine": engine,
           # phenix 产物 MTZ 的建图列名（rotfix 在 phenix 图上用）
           "map_cols_phenix": cfg.get("mtz_columns", {
               "fwt": "2FOFCWT", "phwt": "PH2FOFCWT",
               "delfwt": "FOFCWT", "phdelwt": "PHFOFCWT"})}

    route_names = AUTO_ROUTES if strategy == "auto" else [strategy]
    for rn in route_names:
        if rn not in ROUTES:
            raise SystemExit("unknown strategy: %s (options: %s, auto)" % (
                rn, ", ".join(sorted(ROUTES))))

    candidates = []

    def _run_one(rn):
        rd = os.path.join(workdir, "route_%s" % rn)
        if not os.path.isdir(rd):
            os.makedirs(rd)
        try:
            out = ROUTES[rn](cfg, rd, ctx)
            ev = run_molprobity(out["pdb"], rd, phenix_cfg, mtz=obs_mtz,
                                log=os.path.join(rd, "molprobity_final.log"))
            return {"route": rn, "pdb": out["pdb"], "mtz": out["mtz"],
                    "eval": ev, "info": out["info"]}
        except Exception as e:
            return {"route": rn, "error": "%s\n%s" % (e, traceback.format_exc())}

    with ThreadPoolExecutor(max_workers=len(route_names)) as ex:
        candidates = list(ex.map(_run_one, route_names))

    for c in candidates:
        if "error" in c:
            print("route %s FAILED: %s" % (c["route"], c["error"].splitlines()[0]))
        else:
            print("route %-22s rfree=%s clash=%s rama=%s rotamer=%s" % (
                c["route"], c["eval"].get("rfree"), c["eval"].get("clashscore"),
                c["eval"].get("rama_outliers_pct"),
                c["eval"].get("rotamer_outliers_pct")))

    # ---- 裁决：Rfree 最小者胜；clash 超红线顺位；无人优于起点则保底起点 ----
    redline_pct = float(cfg.get("geometry_redline", {}).get("clash_worse_pct", 20))
    start_clash = baseline.get("clashscore")
    start_rfree = baseline.get("rfree")
    redline = start_clash * (1.0 + redline_pct / 100.0) if start_clash else None
    ok_cands = []
    for c in candidates:
        if "error" in c or c["eval"].get("rfree") is None:
            continue
        clash = c["eval"].get("clashscore")
        c["redline_pass"] = (redline is None or clash is None or clash <= redline)
        ok_cands.append(c)
    eligible = [c for c in ok_cands if c["redline_pass"]]
    if eligible:
        winner = min(eligible, key=lambda c: c["eval"]["rfree"])
        reason = "min rfree among redline-passing routes"
    elif ok_cands:
        winner = min(ok_cands, key=lambda c: c["eval"]["rfree"])
        reason = "all routes violate clash redline; picked min rfree with warning"
    else:
        winner = None
        reason = "all routes failed; keep start model"

    # 保底规则：无候选优于起点 Rfree（已收敛模型，如 4MLI/4Z3U）→ 保留起点
    best_alt = None
    if winner and start_rfree is not None and winner["eval"]["rfree"] >= start_rfree:
        best_alt = winner   # 几何可能更好，记入报告供人工选择
        winner = None
        reason = ("no route beats baseline rfree %.4f; model already at "
                  "local optimum (converged)" % start_rfree)

    if winner:
        final_pdb = winner["pdb"]
        print("SELECTED: %s rfree=%s (%s)" % (
            winner["route"], winner["eval"].get("rfree"), reason))
    else:
        final_pdb = pdb0
        print("SELECTED: start model (%s)" % reason)

    summary = {
        "input_pdb": cfg["pdb"],
        "strategy": strategy,
        "metric_protocol": "phenix.molprobity <pdb> <mtz>",
        "baseline": dict(baseline, pdb=pdb0),
        "phase0": phase0,
        "original_refiner": engine0,
        "polish_engine": engine,
        "geometry_redline": {"clash_worse_pct": redline_pct,
                             "redline_value": redline},
        "candidates": candidates,
        "selected": ({"route": winner["route"], "eval": winner["eval"],
                      "pdb": winner["pdb"]} if winner else None),
        "best_alternative": ({"route": best_alt["route"], "eval": best_alt["eval"],
                              "pdb": best_alt["pdb"]} if best_alt else None),
        "selection_reason": reason,
        "out_pdb": final_pdb,
    }
    sp = os.path.join(workdir, "strategy_summary.json")
    with open(sp, "w") as f:
        json.dump(summary, f, indent=2)
    print("SUMMARY -> %s" % sp)


if __name__ == "__main__":
    main()
