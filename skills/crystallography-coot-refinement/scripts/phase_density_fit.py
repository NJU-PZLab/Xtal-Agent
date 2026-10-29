# -*- coding: utf-8 -*-
"""phase_density_fit.py — 全局密度拟合优化（方法 B：worst-N 迭代局部精修）。

思路：用 coot 逐残基 map-model 相关系数找出拟合最差的 N 个蛋白残基，
批量实空间局部精修（refine_residues + accept），重评分，迭代至收敛。
纯 coot/实空间（合规：不动 refmac/phenix 倒易空间精修）。

输入 params:
  pdb, mtz, mtz_columns, dict_cifs
  refine_weight: "auto" | 数值（默认 auto）
  worst_n:       每轮精修的最差残基数（默认 10）
  max_iters:     最大迭代轮数（默认 2）
  zone_pad:      0=按残基批量精修（默认）；>0=逐残基 refine_zone [resno±pad]
  atom_mask_mode: 0=全原子（默认）；1=主链；2=侧链
  out_pdb

输出 result JSON:
  weight_used, iters: [{iter, n_refined, mean_cc_before, mean_cc_after,
                        refined: [{chain,resno,res_type,cc_before,cc_after}]}],
  converged, out_pdb
"""
import os
import sys

sys.path.insert(0, os.environ.get("COOTJOB_SCRIPTS_DIR", os.getcwd()))
import coot_common as cc

STANDARD = set("ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE "
               "PRO SER THR TRP TYR VAL MSE SEC PYL".split())


def _score_all(imol, imol_map, mask_mode):
    """逐残基 CC。返回 [(cc, chain, resno, ins, resname), ...]（蛋白残基）。"""
    scored = []
    residues = [r for r in cc.iter_residues_fast(imol) if r[3] in STANDARD]
    specs = [[r[0], int(r[1]), r[2]] for r in residues]
    if not specs:
        return scored
    raw = cc.coot_call("map_to_model_correlation_per_residue_py",
                       imol, specs, int(mask_mode), imol_map)
    cc_map = _normalize_cc(raw)
    for r, spec in zip(residues, specs):
        key_variants = [str(spec), "%s%d%s" % (spec[0], spec[1], spec[2]),
                        tuple(spec)]
        val = None
        for k in key_variants:
            if k in cc_map:
                val = cc_map[k]
                break
        if val is None and isinstance(raw, (list, tuple)):
            idx = specs.index(spec)
            if idx < len(raw):
                v = raw[idx]
                val = v[1] if isinstance(v, (list, tuple)) and len(v) >= 2 else v
        if val is not None:
            try:
                scored.append((float(val), r[0], int(r[1]), r[2], r[3]))
            except Exception:
                pass
    return scored


def _normalize_cc(raw):
    """兼容 dict / list 返回格式 -> {key: cc}。"""
    out = {}
    try:
        if hasattr(raw, "items"):
            for k, v in raw.items():
                out[k] = float(v)
        elif isinstance(raw, (list, tuple)):
            for item in raw:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    spec, val = item[0], item[1]
                    if isinstance(spec, (list, tuple)):
                        out[str(list(spec))] = float(val)
                        out[tuple(spec)] = float(val)
                    else:
                        out[str(spec)] = float(val)
    except Exception:
        pass
    return out


def main(params):
    cc.require_files(params, ["pdb", "mtz"])
    imol = cc.read_model(params["pdb"])
    for cif in params.get("dict_cifs", []):
        if os.path.isfile(cif):
            cc.read_dictionary(cif)
    cols = params.get("mtz_columns", {})
    imol_2fofc, _diff = cc.make_maps_from_mtz(
        params["mtz"],
        fwt=cols.get("fwt", "FWT"), phwt=cols.get("phwt", "PHWT"),
        delfwt=cols.get("delfwt", "DELFWT"), phdelwt=cols.get("phdelwt", "PHDELWT"))
    cc.set_refinement_map(imol_2fofc)
    weight_used = cc.setup_scripted_refinement(
        imol_2fofc, weight=params.get("refine_weight", "auto"), imol_model=imol)

    worst_n = int(params.get("worst_n", 10))
    max_iters = int(params.get("max_iters", 2))
    pad = int(params.get("zone_pad", 0))
    mask_mode = int(params.get("atom_mask_mode", 0))
    min_gain = float(params.get("converge_min_gain", 0.0005))

    iters = []
    converged = False
    prev_mean = None
    for it in range(1, max_iters + 1):
        scored = _score_all(imol, imol_2fofc, mask_mode)
        if not scored:
            return cc.fail("no protein residues scored")
        scored.sort()   # CC 升序 = 最差在前
        batch = scored[:worst_n]
        mean_before = sum(b[0] for b in batch) / len(batch)

        if pad > 0:
            for _cc0, ch, rn, ins, _rt in batch:
                cc.refine_zone_accept(imol, ch, max(1, rn - pad), rn + pad, ins)
        else:
            specs = [[ch, rn, ins] for _cc0, ch, rn, ins, _rt in batch]
            cc.refine_residues_accept(imol, specs)

        after = {(r[1], r[2]): r[0] for r in _score_all(imol, imol_2fofc, mask_mode)}
        refined = []
        for cc0, ch, rn, ins, rt in batch:
            refined.append({"chain": ch, "resno": rn, "res_type": rt,
                            "cc_before": round(cc0, 4),
                            "cc_after": round(after.get((ch, rn), cc0), 4)})
        gains = [r["cc_after"] - r["cc_before"] for r in refined]
        mean_after = sum(r["cc_after"] for r in refined) / len(refined)
        iters.append({"iter": it, "n_refined": len(refined),
                      "mean_cc_before": round(mean_before, 4),
                      "mean_cc_after": round(mean_after, 4),
                      "refined": refined})
        if prev_mean is not None and (mean_after - prev_mean) < min_gain:
            converged = True
            break
        prev_mean = mean_after

    out_pdb = params.get("out_pdb", "density_fit.pdb")
    cc.save_model(imol, out_pdb)
    return cc.ok({"phase": "density-fit", "weight_used": weight_used,
                  "iters": iters, "converged": converged, "out_pdb": out_pdb},
                 default_name="density_fit_result.json")


if __name__ == "__main__":
    cc.run_phase(main, cc.load_params())
    cc.exit_clean(0)
