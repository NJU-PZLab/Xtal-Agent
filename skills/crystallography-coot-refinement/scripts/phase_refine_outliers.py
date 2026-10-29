# -*- coding: utf-8 -*-
"""phase_refine_outliers.py — coot 定点 refine molprobity outlier 区域（用户显式触发）。

用途：phenix/refmac 全局精修无法消除的 Rama/clash outlier，用 coot
实空间 refine_zone 逐个定点修复（密度引导）。

输入 params:
  pdb, mtz, mtz_columns, dict_cifs
  zones: [[chain, resno_lo, resno_hi], ...]   待 refine 的残基区间
  delete_waters: [[chain, resno], ...]        与蛋白严重 clash 的水（删除）
  refine_weight: 数值 / "auto"（默认 auto）
  out_pdb

输出 result JSON: zones_done, zones_failed, waters_deleted, out_pdb
"""
import os
import sys

sys.path.insert(0, os.environ.get("COOTJOB_SCRIPTS_DIR", os.getcwd()))
import coot_common as cc


def main(params):
    cc.require_files(params, ["pdb", "mtz"])
    imol = cc.read_model(params["pdb"])
    for cif in params.get("dict_cifs", []):
        if os.path.isfile(cif):
            cc.read_dictionary(cif)
    cols = params.get("mtz_columns", {})
    imol_2fofc, imol_diff = cc.make_maps_from_mtz(
        params["mtz"],
        fwt=cols.get("fwt", "FWT"), phwt=cols.get("phwt", "PHWT"),
        delfwt=cols.get("delfwt", "DELFWT"), phdelwt=cols.get("phdelwt", "PHDELWT"),
    )
    weight = params.get("refine_weight", "auto")
    weight_used = cc.setup_scripted_refinement(imol_2fofc, weight=weight, imol_model=imol)

    # Ramachandran 重约束（修 rama outlier 必备：refine_zone 目标函数默认
    # 无此约束，密度会把主链 phi/psi 钉在张力构象，几何项拉不回）
    rama_on = bool(params.get("rama_restraints", False))
    rama_w = None
    if rama_on:
        cc.coot_call("set_refine_ramachandran_angles", 1)
        rama_w = float(params.get("rama_restraints_weight", 40.0))
        cc.coot_call("set_refine_ramachandran_restraints_weight", rama_w)

    # 1. 删除与蛋白严重 clash 的水（找水噪声，物理上不可能）
    waters_deleted = []
    for spec in params.get("delete_waters", []):
        chain, resno = str(spec[0]), int(spec[1])
        try:
            cc.coot_call("delete_residue", imol, chain, resno, "")
            waters_deleted.append({"chain": chain, "resno": resno})
        except Exception as e:
            waters_deleted.append({"chain": chain, "resno": resno, "error": str(e)})

    # 2. 定点 refine outlier 区域
    zones_done = []
    zones_failed = []
    for z in params.get("zones", []):
        chain, lo, hi = str(z[0]), int(z[1]), int(z[2])
        try:
            cc.refine_zone_accept(imol, chain, lo, hi, "")
            zones_done.append([chain, lo, hi])
        except Exception:
            zones_failed.append([chain, lo, hi])

    out_pdb = params.get("out_pdb", "coot_outliers_refined.pdb")
    cc.save_model(imol, out_pdb)

    return cc.ok({
        "phase": "refine-outliers",
        "weight_used": weight_used,
        "rama_restraints": rama_on,
        "rama_weight": rama_w,
        "zones_done": zones_done,
        "zones_failed": zones_failed,
        "waters_deleted": waters_deleted,
        "out_pdb": out_pdb,
    }, default_name="coot_refine_outliers_result.json")


if __name__ == "__main__":
    cc.run_phase(main, cc.load_params())
    cc.exit_clean(0)
