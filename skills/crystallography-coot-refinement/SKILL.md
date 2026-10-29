---
name: crystallography-coot-refinement
description: Use when refining a protein model with Coot headless mode to lower Rfree. Two-route tournament (with/without waters) - coot-only water addition and real-space refinement, final polish by the deposited model's original refinement program (refmac or phenix, detected from mtz columns), rotfix always last, adjudicated by phenix.molprobity Rfree with geometry red-line and keep-original fallback. Single entry point run_strategy.py.
---

# Crystallography Coot Refinement（无头精修）

精修流程。所有逻辑判断、阈值、禁止操作均已编码在
`scripts/` 的代码中，**禁止 LLM 即兴编写 coot 脚本**。

## 执行入口（唯一，MUST）

```bash
coot --version     # 环境检查
python3 scripts/run_strategy.py --config config.json
```

config 模板见 `scripts/config.example.json`。必填字段：`pdb`、`mtz`、
`resolution`、`ccp4_setup`、`phenix.labels`、`phenix.rfree_label`。

## 架构原则（4Z3U 系列实验确立，MUST）

1. **refmac/phenix 仅用于收尾优化**，且与原沉积模型的精修程序一致
   （自动识别 mtz 列名：`FWT/PHWT/FC_ALL_LS`→refmac；`2FOFCWT/PH2FOFCWT`→phenix；
   可用 `polish_engine` 覆盖）。模型本在其原协议谷底，同协议收尾漂移最小。
2. **加水与实空间精修（RSR）只用 coot**（密度引导，无过拟合能力）。
   加水轮内不做任何倒易空间精修；σ 扫描/轮次评分用 `phenix.molprobity`
   纯打分（不动坐标，与裁决同口径）。
3. **rotfix 永远最后**（在收尾 refmac/phenix 之后）。
4. 有任何可用建图列即**跳过 Phase0**；仅当 mtz 完全无图列时才 Phase0
   refmac（此时收尾引擎视为 refmac）。

## 路线选择（strategy 字段）

```jsonc
{
  "strategy": "auto",   // 推荐 "auto"
  "waters": { "sigma": [3.0, 2.5, 2.0, 1.5], "max_rounds": 3,
              "saturation_min_new": 20, "saturation_min_gain": 0.001,
              "revert_on_bounce": true },
  "geometry_redline": { "clash_worse_pct": 20 }
}
```

- `auto` — 两路并行竞选，唯一变量 = 是否加水：
  - `no_waters`：coot全残基RSR → 收尾(refmac|phenix) → rotfix
  - `waters`：coot加水迭代 → coot全残基RSR → 收尾 → rotfix
- `waters` / `no_waters` — 单跑对应路线
- `fixed` / `waters_refmac` / `waters_refmac_polish` / `waters_fixed` —
  旧命名路线（向后兼容，不推荐）

## 裁决规则（auto，已编码）

1. 起点基线与候选终验统一用 `phenix.molprobity <pdb> <mtz>`
   （fmodel 管线剔除 F-obs outlier；**model_vs_data 不剔 outlier，禁用作裁决**）
2. Rfree 最小者胜；胜者 clashscore 超过起点 ×(1+红线%) 则顺位
3. **无候选优于起点 Rfree → 保底起点模型**（已收敛信号，如 4MLI/4Z3U；
   此时几何最优候选记入 `best_alternative` 供人工选择）

## 流程要点（代码自动执行）

- 加水：coot find_waters σ 扫描（molprobity 纯打分）；饱和停（新增<20 且
  增益<0.001）、回弹退一轮；轮次快照全留
- 收尾：refmac（10 cyc）或 phenix.refine（默认 3 macrocycle），按识别结果
- rotfix：rotalyze 清单 + backrub 模式；密度支持的应变构象保留并报告
- 失败处理：单路线失败记 `error` 不拖垮其他路线

## 经验教训（实测）

- **协议税**：refmac/model_vs_data 不剔 outlier，Rfree 系统性偏高 ~0.02；
  phenix.refine 与 molprobity 同口径（起始读数精确一致）
- **精修漂移与引擎无关**：已收敛模型过任何全局精修，Rfree 单调上升
  （refmac +0.0145/10cyc、phenix +0.0143/3cyc，4Z3U 实测）——漂移源于
  全模型 xyz+B 再平衡，coot 的密度引导局部位移无此问题
- 加水的真实收益在 molprobity 纯打分下可见（4Z3U：+7 个水 -0.0006），
  但已收敛模型上会被后续 RSR+收尾的漂移淹没 → 保底规则正确拦截
- phenix 默认权重对已收敛模型过拟合；旧路线几何收尾用 wxc_scale 0.5/0.3

## 输出物

workdir 下：
- `strategy_summary.json` — baseline、original_refiner、polish_engine、
  candidates（各路线全指标+逐步归因）、selected、selection_reason
- `route_no_waters/` `route_waters/` — 各路线路径日志与中间模型
- `molprobity_start.log` — 起点基线

向用户汇报：起点 vs 选中路线的 Rfree 对比与 molprobity 四项、
落选路线指标（一句话）、rotfix 保留未修残基清单（需人工定夺）。

## 环境约束（coot 0.9.8.96，内嵌 Python 2.7）

- 无头运行：`coot --no-graphics -s <script> --no-guano`（`-s` 必须，`--script` 无效）
- coot 内嵌解释器是 py2.7，unicode 参数需 `_byteify()`（代码已处理）
- 无头 segfault 禁用函数与缺失函数清单见 `scripts/coot_common.py` docstring
- 路径含空格可正常工作（bash -c 调用均已引号化）
