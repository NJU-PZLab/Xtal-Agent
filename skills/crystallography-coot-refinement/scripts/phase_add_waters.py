# -*- coding: utf-8 -*-
"""phase_add_waters.py — coot find_waters 加水（实验性，用户显式触发）。

从指定模型出发，在 2Fo-Fc 图上按 sigma 阈值找水峰，加入模型。
默认参数对齐 coot GUI "Find Waters"：rmsd_cut_off=3.0 sigma。

注意：4JDH 实测加水使 Rfree 变差，固定策略默认不加；本脚本仅在用户
明确要求时使用，加水后必须经 phenix.refine 重算 Rfree 对比。
"""
import os
import sys

sys.path.insert(0, os.environ.get("COOTJOB_SCRIPTS_DIR", os.getcwd()))
import coot_common as cc


def _n_waters(imol):
    """统计模型中 HOH/WAT 残基数。"""
    n = 0
    try:
        info = cc.coot_call("all_residues_with_serial_numbers_py", imol)
        for r in info:
            rname = cc.coot_call("resname_from_serial_number",
                                 imol, str(r[2]), int(r[0]))
            if str(rname) in ("HOH", "WAT"):
                n += 1
    except Exception:
        pass
    return n


def main(params):
    cc.require_files(params, ["pdb", "mtz"])
    imol_model = cc.read_model(params["pdb"])
    cols = params.get("mtz_columns", {})
    imol_2fofc, imol_diff = cc.make_maps_from_mtz(
        params["mtz"],
        fwt=cols.get("fwt", "FWT"), phwt=cols.get("phwt", "PHWT"),
        delfwt=cols.get("delfwt", "DELFWT"), phdelwt=cols.get("phdelwt", "PHDELWT"),
    )
    sigma = float(params.get("sigma", 3.0))
    out_pdb = params.get("out_pdb", "coot_waters.pdb")

    # 可选：放宽/收紧 find_waters 的水-蛋白距离过滤（默认 coot 内部 2.4-3.2 A）
    dmin = params.get("water_dist_min")
    dmax = params.get("water_dist_max")
    if dmin is not None and dmax is not None:
        cc.coot_call("set_ligand_water_to_protein_distance_limits",
                     float(dmin), float(dmax))

    n_before = _n_waters(imol_model)
    # find_waters(imol_map, imol_protein, new_waters_mol_flag=0(并入蛋白分子),
    #             rmsd_cut_off, show_blobs_dialog=0(无头))
    cc.coot_call("find_waters", imol_2fofc, imol_model, 0, sigma, 0)
    n_after = _n_waters(imol_model)

    cc.save_model(imol_model, out_pdb)

    return cc.ok({
        "phase": "add-waters",
        "out_pdb": out_pdb,
        "sigma": sigma,
        "waters_before": n_before,
        "waters_after": n_after,
        "waters_added": n_after - n_before,
    }, default_name="coot_add_waters_result.json")


if __name__ == "__main__":
    cc.run_phase(main, cc.load_params())
    cc.exit_clean(0)
