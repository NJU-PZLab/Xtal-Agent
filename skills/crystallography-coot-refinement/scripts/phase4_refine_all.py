# -*- coding: utf-8 -*-
"""phase4_refine_all.py — 全残基 real-space refine（实验性）。

从最优模型出发，对每条蛋白链的全部残基分 zone refine + accept。
"""
import os
import sys

sys.path.insert(0, os.environ.get("COOTJOB_SCRIPTS_DIR", os.getcwd()))
import coot_common as cc


def main(params):
    cc.require_files(params, ["pdb", "mtz"])
    imol_model = cc.read_model(params["pdb"])
    cols = params.get("mtz_columns", {})
    imol_2fofc, imol_diff = cc.make_maps_from_mtz(
        params["mtz"],
        fwt=cols.get("fwt", "FWT"), phwt=cols.get("phwt", "PHWT"),
        delfwt=cols.get("delfwt", "DELFWT"), phdelwt=cols.get("phdelwt", "PHDELWT"),
    )
    weight = params.get("refine_weight")
    if weight in (None, "", "auto"):
        weight = "auto"
    weight_used = cc.setup_scripted_refinement(imol_2fofc, weight=weight, imol_model=imol_model)

    out_pdb = params.get("out_pdb", "coot_refine_all.pdb")
    zone_size = int(params.get("zone_size", 5))   # 每 zone 5 个残基

    # 全链分 zone
    info = cc.coot_call("all_residues_with_serial_numbers_py", imol_model)
    chain_res = {}
    for r in info:
        chain_id, resno = str(r[2]), int(r[3])
        rname = cc.coot_call("resname_from_serial_number", imol_model, chain_id, int(r[0]))
        if str(rname) in ("HOH", "WAT"):
            continue
        chain_res.setdefault(chain_id, []).append(resno)

    import math
    def centre(chain_id, resno):
        try:
            return cc.coot_call("residue_centre_py", imol_model, chain_id, resno, "")
        except Exception:
            return None

    before = {}
    for chain_id, resnos in chain_res.items():
        for rn in resnos:
            c = centre(chain_id, rn)
            if c:
                before[(chain_id, rn)] = c

    n_zones = 0
    n_fail = 0
    for chain_id, resnos in sorted(chain_res.items()):
        resnos = sorted(resnos)
        i = 0
        while i < len(resnos):
            chunk = resnos[i:i + zone_size]
            lo, hi = chunk[0], chunk[-1]
            try:
                cc.refine_zone_accept(imol_model, chain_id, lo, hi, "")
                n_zones += 1
            except Exception:
                n_fail += 1
            i += zone_size

    # 统计移动
    moved = []
    for (chain_id, rn), b in before.items():
        a = centre(chain_id, rn)
        if a:
            d = math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))
            if d > 0.01:
                moved.append({"chain": chain_id, "resno": rn, "moved_A": round(d, 3)})
    rmsd_all = math.sqrt(sum(m["moved_A"] ** 2 for m in moved) / max(1, len(before))) if moved else 0.0

    cc.save_model(imol_model, out_pdb)

    return cc.ok({
        "phase": "4-all",
        "out_pdb": out_pdb,
        "weight_used": weight_used,
        "zones": n_zones,
        "zones_failed": n_fail,
        "residues_moved": len(moved),
        "total_residues": len(before),
        "centre_rmsd_moved": round(rmsd_all, 4),
        "moved_detail": sorted(moved, key=lambda x: -x["moved_A"])[:20],
    }, default_name="coot_phase4all_result.json")


if __name__ == "__main__":
    cc.run_phase(main, cc.load_params())
    cc.exit_clean(0)
