# -*- coding: utf-8 -*-
"""coot_common.py — 在 Coot 内嵌 Python 解释器中运行的公共模块。

本模块中所有 Coot 函数均已在真机 coot 0.9.8.96（内嵌 Python 2.7.16）
无头模式实测验证。关键实测结论：

- 运行方式（manual §3.10）：coot --no-graphics -s <script>.py --no-guano
- 脚本中 __file__ 未定义（coot 用 exec 跑脚本）；scripts 目录经环境变量
  COOTJOB_SCRIPTS_DIR 传入
- 必须兼容 Python 2.7 语法；json.load 返回 unicode，SWIG char const* 参数
  需 byte str → 一律经 _byteify() 转码
- 参数传递：环境变量 COOTJOB_PARAMS 指向 JSON；结果写 COOTJOB_OUT_JSON
- 无头 segfault 禁用函数：check_chiral_volumes（用 chiral_volume_errors_py）、
  ramachandran_plot_differences、execute_refmac_real（refmac 走外层 refmac5）
- 此版本缺失函数：mutate_chain（用 align_and_mutate）、fit_gap、fit_waters、
  de_clash、map_to_model_correlation_stats_per_residue（用 _range_py）、
  score_rotamers_scm（用 score_rotamers_py）
- 实空间精修必须 refine_zone(...) + accept_regularizement() 才真正动原子
  （仅 set_refinement_immediate_replacement(1) 不够）
"""

import json
import os
import sys
import traceback


def _byteify(obj):
    """py2 下把 json 的 unicode 字符串转为 byte str（SWIG char const* 需要）。"""
    if isinstance(obj, dict):
        return dict((_byteify(k), _byteify(v)) for k, v in obj.items())
    if isinstance(obj, list):
        return [_byteify(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_byteify(v) for v in obj)
    if sys.version_info[0] < 3 and isinstance(obj, unicode):  # noqa: F821
        return obj.encode("utf-8")
    return obj


def load_params():
    """读取外层 orchestrator 传入的 JSON 参数文件。"""
    path = os.environ.get("COOTJOB_PARAMS")
    if not path:
        raise SystemExit("COOTJOB_PARAMS not set")
    with open(path) as f:
        return _byteify(json.load(f))


def out_path(default_name):
    return os.environ.get("COOTJOB_OUT_JSON",
                          os.path.join(os.getcwd(), default_name))


def write_result(payload, default_name="coot_result.json"):
    path = out_path(default_name)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    return path


def fail(msg, **extra):
    payload = {"ok": False, "error": msg}
    payload.update(extra)
    path = write_result(payload)
    print("COOTJOB_ERROR: %s -> %s" % (msg, path))
    sys.stdout.flush()
    raise SystemExit(1)


def ok(payload, default_name="coot_result.json"):
    payload = dict(payload)
    payload["ok"] = True
    path = write_result(payload, default_name)
    print("COOTJOB_OK -> %s" % path)
    sys.stdout.flush()
    return path


# ---- Coot 函数调用封装 ----


def coot_call(name, *args):
    """按名字调用 Coot 全局函数（py2/py3 兼容）。"""
    fn = globals().get(name)
    if fn is None:
        try:
            import builtins as _b
        except ImportError:
            import __builtin__ as _b
        fn = getattr(_b, name, None)
    if fn is None:
        import coot as _coot
        fn = getattr(_coot, name, None)
    if fn is None:
        raise RuntimeError("coot function not available: %s" % name)
    return fn(*args)


def require_files(params, keys):
    missing = [k for k in keys if not params.get(k)]
    if missing:
        fail("missing required params: %s" % ", ".join(missing))
    for k in keys:
        p = params[k]
        if not os.path.isfile(p):
            fail("input file not found: %s=%s" % (k, p))


def read_model(pdb_path):
    """read-pdb。返回 imol。实测 OK。"""
    imol = coot_call("read_pdb", pdb_path)
    if imol is None or imol < 0:
        fail("read_pdb failed: %s" % pdb_path)
    return imol


def read_dictionary(cif_path):
    """read-cif-dictionary。实测 OK。"""
    coot_call("read_cif_dictionary", cif_path)


def make_maps_from_mtz(mtz_path,
                       fwt="FWT", phwt="PHWT",
                       delfwt="DELFWT", phdelwt="PHDELWT"):
    """auto-read-make-and-draw-maps-from-mtz。实测 OK。

    返回 (imol_2fofc, imol_diff)。实测返回 4 元组，[0]=2Fo-Fc, [1]=diff。
    """
    coot_call("set_auto_read_column_labels", fwt, phwt, 0)
    coot_call("set_auto_read_column_labels", delfwt, phdelwt, 1)
    coot_call("set_auto_read_do_difference_map_too", 1)
    imols = coot_call("auto_read_make_and_draw_maps_from_mtz", mtz_path)
    if not imols or len(imols) < 2:
        fail("auto_read_make_and_draw_maps_from_mtz failed: %s" % mtz_path)
    return imols[0], imols[1]


def set_refinement_map(imol_map):
    """set-imol-refinement-map。实测 OK。"""
    coot_call("set_imol_refinement_map", imol_map)


def save_model(imol, pdb_path):
    """write-pdb-file。实测 OK。"""
    coot_call("write_pdb_file", imol, pdb_path)


def setup_scripted_refinement(imol_map, weight=None, imol_model=None):
    """脚本化实空间精修的必备初始化。

    - set_imol_refinement_map: 指定精修图
    - set_refinement_immediate_replacement(1): 脚本模式必须（manual 原文）
    - weight: 数值 / "auto"（estimate_map_weight 自动估测，实测 4JDH→74.6）/ None（默认 60）

    返回实际使用的 weight。
    """
    set_refinement_map(imol_map)
    coot_call("set_refinement_immediate_replacement", 1)
    if weight == "auto":
        # estimate_map_weight(imol_map) 实测 1 参数，返回 float
        w = coot_call("estimate_map_weight", imol_map)
        if w is not None and float(w) > 0:
            weight = float(w)
        else:
            weight = 60.0
    if weight is not None:
        coot_call("set_matrix", float(weight))
    return weight


def refine_zone_accept(imol, chain_id, resno1, resno2, ins_code=""):
    """refine_zone + accept_regularizement。

    实测：仅 set_refinement_immediate_replacement(1) 不够，
    必须显式 accept_regularizement() 原子才真正移动
    （coot 内部 with_auto_accept 宏的模式）。
    """
    coot_call("refine_zone", imol, chain_id, resno1, resno2, ins_code)
    coot_call("accept_regularizement")


def refine_residues_accept(imol, specs):
    """refine_residues_py + accept_regularizement。

    specs: [[chain, resno, ins], ...]
    """
    coot_call("refine_residues_py", imol, specs)
    coot_call("accept_regularizement")


def iter_residues(imol):
    """遍历全模型残基。实测 OK。

    用 n_chains + chain_id_py + chain_n_residues + resname_from_serial_number。
    产出 (chain_id, resno, ins_code, resname)。
    """
    n = coot_call("n_chains", imol)
    for i in range(int(n)):
        chain_id = coot_call("chain_id_py", imol, i)
        try:
            nres = int(coot_call("chain_n_residues", chain_id, imol))
        except Exception:
            continue
        for s in range(nres):
            try:
                rname = coot_call("resname_from_serial_number", imol, chain_id, s)
                info = coot_call("all_residues_with_serial_numbers_py", imol)
                # all_residues... 返回 [[serial, is_chain, chain, resno, ins], ...]
                # 直接按 serial 索引更稳
                rec = info[s] if s < len(info) else None
                if rec and rec[2] == chain_id:
                    yield chain_id, int(rec[3]), str(rec[4]), str(rname)
                else:
                    # 退化：按 serial 查 resno 不可得，用 s+1 估算
                    yield chain_id, s + 1, "", str(rname)
            except Exception:
                continue


def iter_residues_fast(imol):
    """更稳的遍历：一次取 all_residues_with_serial_numbers_py。

    实测返回 [[serial, is_protein_flag, chain_id, resno, ins_code], ...]。
    产出 (chain_id, resno, ins_code, resname)。
    """
    info = coot_call("all_residues_with_serial_numbers_py", imol)
    for rec in info:
        try:
            serial, _flag, chain_id, resno, ins_code = rec[0], rec[1], rec[2], rec[3], rec[4]
            rname = coot_call("resname_from_serial_number", imol, chain_id, int(serial))
            yield str(chain_id), int(resno), str(ins_code), str(rname)
        except Exception:
            continue


def exit_clean(code=0):
    sys.stdout.flush()
    sys.stderr.flush()
    raise SystemExit(code)


def run_phase(fn, params, default_out="coot_result.json"):
    try:
        return fn(params)
    except SystemExit:
        raise
    except Exception:
        fail("exception:\n%s" % traceback.format_exc())
