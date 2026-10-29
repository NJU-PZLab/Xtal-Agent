# -*- coding: utf-8 -*-
"""phase4_rotamers.py — Rotamer outlier 修复（4JDH 实测验证版）。

流程（用户定稿）：
  1. 打开 backrub rotamer 模式：set_rotamer_search_mode(ROTAMERSEARCHLOWRES=2)
     （常量实测 AUTOMATIC=0/HIGHRES=1/LOWRES=2；manual §5.12.1.1）
  2. 目标清单来自 phenix.rotalyze（MolProbity 标准；coot score_rotamers_py
     密度扫描找不到此类 outlier，实测扫到 0 个 vs rotalyze 18 个）
  3. 对每个 outlier 按密度分流（score_rotamers_py best 密度分）：
     - 密度 >= max_density_to_fix（默认 0.5）：真实应变构象（数据支撑），
       **不修**，记入 density_supported 列表向用户报告
       （4JDH 实测：强改这类 Rfree 0.2447→0.2528）
     - 密度 < 0.5：弱密度柔性侧链，**直接指定构象（clash 感知，试错在副本上进行）**：
       试设一律作用于试设副本分子（imol_trial），clash 检查用副本残基 vs 真实分子
       当前邻原子距离（residues_near_residue_py + residue_info_py，重原子
       >= clash_min_dist 默认 2.6 Å 为无 clash）；找到无 clash 候选才在真实分子上
       设定；**全部候选都 clash 则真实分子保持原构象不动**，记入
       density_supported 报告用户（4JDH 实测：MET96/MET107 所有正典候选
       都与 VAL119/彼此 clash——堆积口袋的稀有构象是打包所需的，强改必撞，
       clashscore 7.31→13.95 的教训）。**不做任何后续 refine**（refine 拉回
       稀有构象并扰动主链；纯几何 regularize weight=0 也禁用——侧链漂移）

输入 params:
  pdb, mtz, mtz_columns, dict_cifs
  problem_list_json（必需：rotalyze 清单，{"problem":{"rotamer":[{chain,resno,...}]}}）
  max_density_to_fix（默认 0.5）
  min_canonical_prob（默认 5.0，单位 %）
  clash_min_dist（默认 2.6 Å，重原子最小允许距离）
  out_pdb

输出 result JSON:
  outliers_found, density_supported[], fixed[], out_pdb
"""

import math
import os
import sys

sys.path.insert(0, os.environ.get("COOTJOB_SCRIPTS_DIR", os.getcwd()))
import coot_common as cc


def _score_best(scores):
    """score_rotamers_py 返回 [[name, 概率%, 密度分, ...], ...]，取最大密度分。"""
    best = None
    for s in scores or []:
        try:
            d = float(s[2])
            if best is None or d > best:
                best = d
        except Exception:
            continue
    return best


def _dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def _residue_atoms(imol, chain, resno, ins, side_only=True):
    """residue_info_py -> [(atom_name, (x,y,z))]，默认只侧链重原子。"""
    info = cc.coot_call("residue_info_py", imol, chain, resno, ins) or []
    main = ("N", "CA", "C", "O", "OXT")
    out = []
    for atom in info:
        name = atom[0][0].strip()
        if name.startswith("H"):
            continue
        if side_only and name in main:
            continue
        out.append((name, atom[2]))
    if not out:   # GLY/ALA 无侧链
        out = [(a[0][0].strip(), a[2]) for a in info
               if not a[0][0].strip().startswith("H")]
    return out


def _min_contact_dist_cross(imol_trial, chain, resno, ins,
                            imol_real, radius=4.5):
    """试设副本中的残基侧链 vs 真实分子当前邻残基重原子的最小距离。"""
    mine = _residue_atoms(imol_trial, chain, resno, ins)
    near = cc.coot_call("residues_near_residue_py",
                        imol_real, [chain, resno, ins], radius) or []
    worst = 99.0
    worst_pair = None
    for nr in near:
        nch, nres = nr[0], int(nr[1])
        nins = nr[2] if len(nr) > 2 else ""
        if nch == chain and nres == resno:
            continue
        for n2, c2 in _residue_atoms(imol_real, nch, nres, nins, side_only=False):
            for n1, c1 in mine:
                d = _dist(c1, c2)
                if d < worst:
                    worst = d
                    worst_pair = "%s:%s%d:%s" % (n1, nch, nres, n2)
    return worst, worst_pair


def main(params):
    cc.require_files(params, ["pdb", "mtz"])

    imol_model = cc.read_model(params["pdb"])
    for cif in params.get("dict_cifs", []):
        if os.path.isfile(cif):
            cc.read_dictionary(cif)
    cols = params.get("mtz_columns", {})
    imol_2fofc, imol_diff = cc.make_maps_from_mtz(
        params["mtz"],
        fwt=cols.get("fwt", "FWT"),
        phwt=cols.get("phwt", "PHWT"),
        delfwt=cols.get("delfwt", "DELFWT"),
        phdelwt=cols.get("phdelwt", "PHDELWT"),
    )
    cc.set_refinement_map(imol_2fofc)

    # 1. 打开 backrub rotamer 模式（用户定稿；备用 auto_fit 路径也受益）
    cc.coot_call("set_rotamer_search_mode", 2)   # ROTAMERSEARCHLOWRES=2 实测

    max_density = float(params.get("max_density_to_fix", 0.5))
    min_prob = float(params.get("min_canonical_prob", 5.0))
    clash_min = float(params.get("clash_min_dist", 2.6))

    # 试设副本：所有 rotamer 试错在副本上做，真实分子只接受 clash-free 结果
    imol_trial = cc.read_model(params["pdb"])

    # 2. 读 rotalyze 清单
    import json
    pl_json = params.get("problem_list_json")
    if not pl_json or not os.path.isfile(pl_json):
        return cc.fail("problem_list_json (rotalyze outliers) is required")
    with open(pl_json) as f:
        pl = cc._byteify(json.load(f))   # py2 json -> unicode，SWIG 需 byte str
    targets = [(t["chain"], int(t["resno"]), t.get("ins_code", ""),
                t.get("res_type", ""))
               for t in pl.get("problem", {}).get("rotamer", [])]

    density_supported = []
    fixed = []
    n_fixed = 0
    for chain_id, resno, ins_code, rname in targets:
        try:
            # 3. 密度分流
            sc0 = cc.coot_call(
                "score_rotamers_py",
                imol_model, chain_id, resno, ins_code, "",
                imol_2fofc, 1, 0.01)
            before = _score_best(sc0)
            if before is not None and before >= max_density:
                density_supported.append({
                    "chain": chain_id, "resno": resno, "res_type": rname,
                    "density": before,
                    "note": "density-supported strained conformer, kept",
                })
                continue

            # 无密度支持：直接指定构象（clash 感知，逐个试设）
            sc_all = cc.coot_call(
                "score_rotamers_py",
                imol_model, chain_id, resno, ins_code, "",
                imol_2fofc, 1, 0.0001)   # 列出全部候选
            cands = []
            for s in sc_all or []:
                try:
                    name, prob, dens = s[0], float(s[1]), float(s[2])
                    if prob >= min_prob:
                        cands.append((dens, prob, name))
                except Exception:
                    continue
            if not cands:
                fixed.append({"chain": chain_id, "resno": resno,
                              "res_type": rname, "before": before,
                              "error": "no canonical candidate"})
                continue
            cands.sort(reverse=True)   # 密度最佳优先

            # 副本上逐个试设 + clash 检查（对真实分子当前状态）
            chosen = None
            tried = []
            for dens, prob, name in cands:
                cc.coot_call("set_residue_to_rotamer_name",
                             imol_trial, chain_id, resno, ins_code, "", name)
                d_min, pair = _min_contact_dist_cross(
                    imol_trial, chain_id, resno, ins_code, imol_model)
                tried.append({"rotamer": name.strip(), "prob_pct": prob,
                              "density": dens, "min_dist": round(d_min, 2)})
                if d_min >= clash_min:
                    chosen = (dens, prob, name, d_min)
                    break
            if chosen is None:
                # 全部候选 clash：真实分子保持原构象，报告用户
                density_supported.append({
                    "chain": chain_id, "resno": resno, "res_type": rname,
                    "density": before,
                    "note": "all canonical rotamers clash; kept original, needs human review",
                    "candidates_tried": tried,
                })
                continue
            dens, prob, name, d_min = chosen
            # 真实分子上一次性设定选中的构象
            cc.coot_call("set_residue_to_rotamer_name",
                         imol_model, chain_id, resno, ins_code, "", name)
            n_fixed += 1
            fixed.append({
                "chain": chain_id, "resno": resno, "res_type": rname,
                "before": before, "rotamer": name.strip(),
                "prob_pct": prob, "density": dens,
                "min_dist": round(d_min, 2),
                "candidates_tried": tried,
            })
        except Exception as e:
            fixed.append({"chain": chain_id, "resno": resno,
                          "res_type": rname, "error": str(e)})

    out_pdb = params.get("out_pdb", "coot_rotamers_fixed.pdb")
    cc.save_model(imol_model, out_pdb)

    return cc.ok({
        "phase": "4-rotamers",
        "method": "direct-assign (backrub mode on)",
        "outliers_found": len(targets),
        "n_fixed": n_fixed,
        "density_supported": density_supported,
        "fixed": fixed,
        "out_pdb": out_pdb,
    }, default_name="coot_phase4rotamers_result.json")


if __name__ == "__main__":
    cc.run_phase(main, cc.load_params())
    cc.exit_clean(0)
