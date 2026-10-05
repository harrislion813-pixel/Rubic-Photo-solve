# HTM / QTM 下一步优化工作包结果

更新日期：2026-10-03（Asia/Shanghai）。对应[执行方案](../../htm-qtm-next-speed-plan-2026-10-02.md)。本文件区分完整排除层性能、真实原生正确性、桥接合约和完整请求验收；正式六状态 72 请求已完成，最终结论见[实施报告](../../htm-qtm-next-speed-report-2026-10-03.md)。HTM/QTM 均有可重复单状态退化，速度变体不采用默认；保守默认实际包另作功能和身份核对。

| 工作包 | 已有结果 | 当前决定 |
| --- | --- | --- |
| P0 | 已冻结原始身份、受控对照、观测和 72 条完整请求；补齐资源修复门禁及包身份 | 原冻结 335 文件及 17 资产/缓存重新核对不变，全部原始错误保留 |
| H1 | 六状态页面首候选中位数下降 50.61%–62.31%；initial-12 严格中位数 +174.64%，两次配对退化 | 20% 交付目标通过，完整请求门槛失败；默认 early off，保留显式实验开关 |
| H2 | 固定数组 + stable_sort、固定数组 + 稳定插入排序均无净收益 | 两个变体均拒绝；生产保留原容器和排序 |
| Q1 | 同树层改善 28.96%、28.35%；QTM 72 矩阵中的 PAR-2 均值下降 21.71%，initial-2 严格中位数 +47.49%且两次配对退化 | 单项通过，完整请求门槛失败；默认 generic，full-strong 仅显式实验 |
| Q2 方向短片 | 12 次候选请求全部最终成本 24；首候选差异较小，没有上界改善 | 保留 legacy 默认；short-slices 仅作独立实验开关 |
| Q2 late Tail | 真实正确性门禁通过；生产桥接 12 次 AB 全部严格完成，但真实改进为 0，未执行 Tail 的状态也呈相近耗时变化 | 本轮不采用，保持 off 默认 |
| P1 Portable PGO | HTM/QTM 构建支持和真实独立训练脚本已补齐；排除六验收状态检查通过 | 本轮未训练、未编译 PGO、未测 PGO 性能，生产仍为普通 Portable O3/LTO |
| P2 | 本轮未增加新剪枝、大表或任务分发算法 | 暂不扩展 |

## P0：原始冻结与受控对照

[baseline-identity.json](baseline-identity.json) 记录 HEAD `6754a8c2cb9b87860f594bba0d59326ef260aceb`、Windows 11 / 16 逻辑 CPU / 15 个总额度、源码/EXE/资产/缓存散列，冻结副本位于 `.codex/next-speed/baseline`。顺序固定 AB、BA、AB；完整层每次最多 5 秒，正式请求最多 30 秒，状态顺序 `initial-1、12、2、5、8、16`。缓存条件为新进程、暖 OS 文件缓存，未清磁盘缓存。

历史冻结命令如下。现存冻结副本不可覆盖；重新冻结当前源码不能替代这份原始对照。

```powershell
.venv\Scripts\python.exe tests/freeze_next_speed.py --threads 15 --snapshot .codex/next-speed/baseline --output docs/benchmarks/next-speed-2026-10-02/baseline-identity.json
```

正式 HTM 请求另外使用 `.codex/next-speed/baseline-observed`，详见[controlled-baseline-identity.json](controlled-baseline-identity.json) 与[controlled-baseline.patch](controlled-baseline.patch)。该对照保留同步候选发布，仅加入观测和相同资源约束：15 总额度中候选占 1、证明先占 14，候选结束后在后续层边界恢复至 15；额度 1 串行执行候选与证明并沿用同一绝对 deadline。原冻结副本及原 EXE 身份仍保留，两份对照不得混称为同一二进制。

[controlled-baseline-contracts.xml](controlled-baseline-contracts.xml) 的 21 项全部通过，身份清单明确记录 `actual_solver_calls=0`：主要是 mock/AST/桥接约束验证，另有 Windows 当前进程内存 API 烟测，不是默认请求速度或工作集验收。新增门禁包含 QTM 客户端终态透传/冻结、关键 memory helper 与 H1 一致、峰值 max 汇总和去除 P0 观测后的 QTM bridge AST 等价。

后续[受控实际包身份与浅状态烟测](controlled-baseline-package-identity.json)实际验证 HTM/QTM 各一个新进程的 R 单步请求，均严格完成成本 1、独立回放正确，并确认 packaged terminal/events/15 总额度字段。HTM 复用全部 12 个 C++ 源 SHA 与受控副本相符的 Portable 普通 O3/LTO EXE `f85a87aca23957fdca40e5c677b366d8713dc943612dd6cdb4df891ba587338f`，QTM 保留原冻结 EXE，五个关键 Python 模块均打包自 observed；原冻结副本不动。这是后续 Symmetry 初始化暂停 checkpoint 修复之前的包证据，不能替代修复后 native 资源门禁、重新构建身份或最终 72 请求验收。复现见[受控基线验证说明](controlled-baseline-verification.md)。

该阶段[Python 契约](final-python-contracts.xml)为 78 项通过、0 fail/skip、1 个 pytest cache 写入权限警告（[原日志](final-python-contracts.log)，5.98 秒；XML 开始时间 `2026-10-03 01:41:37 +08:00`），只代表当时的 Python/桥接源码范围。后续 Symmetry checkpoint 修复已有[3 项真实 loader 门禁](qtm-loader-repaired-gates-final.xml)、[19 项资产/期限门禁](qtm-loader-repaired-assets.xml)及[bounded reuse（归档）](../../evidence-archive-2026-10-06.md#file-d7430d098f6a)，均通过；不能把旧 Python 结果冒称为新原生资源门禁。

H1 的[53 项合约结果](htm-h1-final-contracts.xml)与[真实原生动态额度记录](htm-h1-dynamic-gates.json)提供功能证据。后者实际使用 HTM EXE SHA `f85a87aca23957fdca40e5c677b366d8713dc943612dd6cdb4df891ba587338f`，覆盖 1/2/3 额度、取消及浅状态复用，其等待和取消耗时不是性能收益。完整交付与严格确认分别由[有效矩阵（归档）](../../evidence-archive-2026-10-06.md#file-d2b4557ffd6f)和[独立汇总（归档）](../../evidence-archive-2026-10-06.md#file-f89b30c39b6b)确定；最终默认回退后的[80 项合约](default-python-contracts-final.xml)另行通过。

## H2：两种排序消融均拒绝

两次实验均使用相同冻结 HTM 对照、15 线程、`legal-20260927-0 / bound 16` 与 `known18 / bound 16`，每版本每状态 3 次，顺序 AB、BA、AB，每请求最多 5 秒。两个层每次均完整排除，无候选上界注入，采用绕过证明缓存的 legacy 协议。

| 变体 | 状态 | 基线墙钟中位数 / 秒 | 变体墙钟中位数 / 秒 | 变体相对基线 |
| --- | --- | ---: | ---: | ---: |
| 固定数组 + stable_sort | legal-20260927-0 | 1.417043 | 1.483574 | +4.70% |
| 固定数组 + stable_sort | known18 | 1.429353 | 1.456929 | +1.93% |
| 固定数组 + 稳定插入排序 | legal-20260927-0 | 1.534990 | 1.562112 | +1.77% |
| 固定数组 + 稳定插入排序 | known18 | 1.489930 | 1.515139 | +1.69% |

[h2-fixed-stable.json（归档）](../../evidence-archive-2026-10-06.md#file-0d7ba6a644c1) 必须保留原失败：`AssertionError: same-tree counter changed: legal-20260927-0/phase1_queries`，原 `summary` 为空，原文件没有 `adopt` 字段。表中该变体两项中位数来自这份失败记录已保存的 12 次原始墙钟静态汇总，未为此重跑求解，也没有把原失败改写成通过。

复核发现六次完成帧的生成量和各类拒绝量完全一致：两状态生成量分别为 `194928936`、`201407415`。查询计数包含动态任务重检，不能与唯一展开/拒绝量混为同树判据。例如 legal 层的 phase1 查询范围为 `332588149..332588944`，known18 层为 `325120288..325121701`。这是原检查把查询量也要求逐项完全一致导致的失败；当前比较脚本保留查询范围，使用生成和拒绝计数核对树覆盖。固定数组 + 插入排序的[原始记录（归档）](../../evidence-archive-2026-10-06.md#file-687362091c50)采用该判据、无失败，`adopt=false`。两个变体均未达到至少 5% 改善，因此无需依靠查询计数解释来采用它们。

两变体共用消融源 SHA `3C3E2BD95B21D44AA2B10EA50BC68F164C01B05318DF3EDD9A712058CE76EB02`，通过编译宏分别选择排序。原 EXE SHA 为 stable `6a2056d127fd9ef5fdc873dec196c782d3b8f2a0d765cdcc05fdae24fd2ab29e`、insertion `4863b0ed3034c7c2ccee3781d51f32f3a3b9eabb8d09d8ea2ce807239df952ba`；冻结基线为 `e6c0574cdecce36a30cfe572bb6a13a47228247c1fe05f520e77992d5f107797`。

[prepare_htm_sort_ablation.py](../../../tests/prepare_htm_sort_ablation.py)可从冻结源精确重建上述消融源。下面使用新的输出目录，避免覆盖历史副本；编译器、参数与 EXE 散列仍需按重建时实际身份保存。

```powershell
.venv\Scripts\python.exe tests/prepare_htm_sort_ablation.py --baseline .codex/next-speed/baseline/native/htm --output .codex/next-speed/h2-repro-source
& .codex/next-speed/h2-repro-source/build.ps1 -Portable -CandidateSort FixedStable -OutputDirectory .codex/next-speed/h2-repro-stable
& .codex/next-speed/h2-repro-source/build.ps1 -Portable -CandidateSort FixedInsertion -OutputDirectory .codex/next-speed/h2-repro-insertion
.venv\Scripts\python.exe tests/benchmark_next_speed_pair.py --metric HTM --baseline .codex/next-speed/baseline/native/htm/build/cube_solver_htm.exe --current .codex/next-speed/h2-repro-stable/cube_solver_htm.exe --case-a legal-20260927-0 --case-b known18 --pgo-bound 16 --known-bound 16 --threads 15 --output .codex/next-speed/h2-repro-stable.json
.venv\Scripts\python.exe tests/benchmark_next_speed_pair.py --metric HTM --baseline .codex/next-speed/baseline/native/htm/build/cube_solver_htm.exe --current .codex/next-speed/h2-repro-insertion/cube_solver_htm.exe --case-a legal-20260927-0 --case-b known18 --pgo-bound 16 --known-bound 16 --threads 15 --output .codex/next-speed/h2-repro-insertion.json
```

## Q1：完整层通过，完整请求失败后关闭默认

[q1-pair.json（归档）](../../evidence-archive-2026-10-06.md#file-6bce614bc8c2)记录 15 线程、eager 完整资产、关闭候选/证明缓存/方向变化、相同完整层、AB、BA、AB 共 12 次请求。专用路径的两项墙钟改善均超过单项门槛；原 `adopt` 仅按暖缓存完整排除层判断，不代替完整请求验收。正式矩阵发现 initial-2 可重复退化，因此最终默认为 generic，专用代码仅由 `CUBE_QTM_EXPANSION=full-strong` 或原生同名参数显式启用。

| 状态 / 成本界 | 基线中位数 / 秒 | full-strong 中位数 / 秒 | 耗时下降 | 相同生成量 |
| --- | ---: | ---: | ---: | ---: |
| pgo16 / 19 | 1.612170 | 1.145269 | 28.96% | 125074875 |
| known18 / 18 | 0.178112 | 0.127626 | 28.35% | 13660095 |

各类拒绝量完全一致，查询范围另报。原基线 EXE SHA `8c2912c43e267ea32ac9daea77902bc2258d91ef35f6a456e92c165734d5376a`，Q1 EXE SHA `18b45f69ae55d7eb44e245aeb31929080e226c344edf149828e9bfcdc5d9d823`。两者均为普通 Portable O3/LTO，未混入 PGO。层入口根据不可变资产快照选择路径；缺失、部分、损坏资产及非默认实验配置保留 generic。

[q1-gates-final.xml](q1-gates-final.xml)为 15 项通过、0 skip；[qtm-final-gates.xml](qtm-final-gates.xml)为 38 项通过、0 skip，覆盖独立浅层 oracle、半转成本、全部 cutoff 与接受节点坐标字段、完整/部分/缺失/损坏资产、配置回退、1/2/3 额度、取消及原 deadline。前一份[q1-gates.xml](q1-gates.xml)仍保留 1 个原失败：测试未加载 Tail，却错误要求 profile 为 `strong`，实际正确返回 `strong-no-tail`；修正期望后才取得 final 结果。

这些门禁有明确时间和源码范围：38 项最终门禁记录来自 10 月 2 日，在 10 月 3 日补候选末端取消/deadline 检查之前；后续修改的真实 Tail 增量门禁见下一节，不能把旧 38 项记录声称为对后来全部源码的重新测试。

```powershell
.venv\Scripts\python.exe tests/benchmark_next_speed_pair.py --metric QTM --baseline .codex/next-speed/baseline/native/qtm/build/cube_solver_qtm.exe --current .codex/next-speed/q1-full-strong/cube_solver_qtm.exe --current-extra=--qtm-expansion=full-strong --pgo-bound 19 --known-bound 18 --threads 15 --output .codex/next-speed/q1-repro.json
$env:QTM_TEST_BINARY = (Resolve-Path .codex/next-speed/q1-full-strong/cube_solver_qtm.exe).Path
$env:REQUIRE_QTM_BINARY = '1'
$env:REQUIRE_QTM_STRONG = '1'
.venv\Scripts\python.exe -m pytest tests/test_qtm_hotpath.py -q -p no:cacheprovider --junitxml=.codex/next-speed/q1-gates-repro.xml
```

## Q2：方向短片与 late Tail 均拒绝默认采用

[q2-candidate-schedule.json](q2-candidate-schedule.json)使用相同 QTM EXE 和完整 phase1/Tail，候选额度固定为 1，总搜索预算每次 3 秒。`initial-1、12` × 两调度 × 3 次，共 12 请求、36 秒名义候选预算，顺序 AB、BA、AB；每次交付公式均独立重放并重算 QTM 成本。

| 状态 | legacy 首候选中位数 / 秒 | short-slices 首候选中位数 / 秒 | 最终成本 |
| --- | ---: | ---: | --- |
| initial-1 | 0.0545003 | 0.0489799 | 两版本各三次均为 24 |
| initial-12 | 0.0423706 | 0.0422331 | 两版本各三次均为 24 |

初候选差异分别约 5.52 毫秒、0.14 毫秒，没有降低上界，且此实验只测候选器，未证明完整请求加速；不采用 short-slices 默认。保留 `CUBE_QTM_CANDIDATE_SCHEDULE=legacy`。

```powershell
.venv\Scripts\python.exe tests/benchmark_next_speed_candidates.py --binary native/qtm/build/cube_solver_qtm.exe --cases initial-1,initial-12 --output .codex/next-speed/q2-schedule-repro.json
```

[qtm-tail-gates.xml](qtm-tail-gates.xml)记录 2 项通过、0 skip，其中一项为两引擎独立训练集排除检查，另一项通过[真实 C++ API harness](../../../tests/qtm_tail_gate.cpp)执行 Tail 改进。harness 覆盖 4 个直接调用场景（真实替换、内部取消、请求取消、已过绝对 deadline）及 1/2/3 额度 × 成功/取消/期限共 9 个 late-adoption 求解场景；每个求解场景只尝试一次、真实窗口替换大于 0、额度未超限，取消/期限场景不签最短证明，Python 独立重放合法。为消除浅层证明抢先结束造成的测试时序竞争，harness 使用测试协调器等待真实改进线程返回；其耗时不是产品性能证据。

实现仅在层边界复用候选额度，捕获不可变 Tail 快照并持有到线程 join，预算至多 0.2 秒且受原请求 deadline 限制；发布前检查内部取消、请求取消和期限。默认 `CUBE_QTM_LATE_TAIL_IMPROVEMENT=off`。

[q2-late-tail-production.json（归档）](../../evidence-archive-2026-10-06.md#file-3576f55937fc)与[原始日志](q2-late-tail-production.log)已完成独立生产桥接 AB：两个状态 × off/on × 三次，共 12 请求，固定 AB、BA、AB 顺序、15 总额度、默认 staged 配置，每次新建原生进程、无注入 incumbent、不复用证明。实际 EXE SHA 为 `9f71a1b72b4fb43f3079f4027435253872c741bff6b57ac62530303d3eb5795f`。12 次全部在原 30 秒期限内严格完成，`failures=[]`，无新超时；initial-1 的最终成本均为 22，initial-12 均为 20。

| 状态 | off 三次完整请求耗时 / 秒 | on 三次完整请求耗时 / 秒 | off / on 中位数 / 秒 | on/off 中位数比 | on 尝试 / 改进次数 |
| --- | --- | --- | --- | ---: | --- |
| initial-1 | 14.015 / 24.578 / 26.531 | 17.578 / 13.015 / 27.125 | 24.578 / 17.578 | 0.715192 | [1,1,1] / [0,0,0] |
| initial-12 | 11.344 / 4.250 / 13.640 | 9.297 / 8.250 / 5.734 | 11.344 / 8.250 | 0.727257 | [0,0,0] / [0,0,0] |

所有请求成功，因此本次 PAR-2 与完整请求时间相同；initial-1 的 off/on 均值为 `21.708000 / 19.239333` 秒，initial-12 为 `9.744667 / 7.760333` 秒。完整请求时间包含初始化、加载准入和搜索，终点是生产桥接收到原生终帧；不是页面轮询观察时间，也不是仅搜索计时。

此次方法有效：12 条 ready 均为 `warm_reused=false`，深拷贝保留启动时的 base / Tail depth 0；每请求均有 strong、Tail 两阶段 `memory_admission admitted=true`，随后实际 `asset_ready` 与 `asset_adopted`，最终 strong/Tail depth 8 被采用且完整 strong 展开量大于 0。所有原生候选和终态公式均按冻结 Facelets 独立重放、重算 QTM 成本；raw 合计 78 条含公式事件，无成本错误。所有 `thread_activity` 的 loader_reserved + candidate + proof 均不超过 15，候选不超过 1。采用事件的剩余期限随启动时固定的原 30 秒 deadline 减少，没有就绪后重置；全部终帧 `strict_success=true`。原生进程生命周期工作集峰值范围为 `3,709,059,072..3,709,255,680` 字节，off/on 峰值基本一致。

**本轮拒绝默认启用 late Tail。** initial-1 虽每次真实尝试一次，但都未降低候选上界，局部改进实际耗时仅 `0.000034 / 0.000076 / 0.000046` 秒；initial-12 的三次 on 根本未执行 late Tail，却出现近似的中位数比。因此不能把约 28% 的表面中位数下降归因于 Tail 改进。原始耗时离散明显，staged 完整请求的资产采用时点和展开量也不同；这组记录不是同树吞吐实验。保留全部三次、相同终态和零改进事实，采用决定维持 off，不宣称已取得该变体的完整求解提速。

此前[q2-late-tail-unmanaged-loader-attempt.json（归档）](../../evidence-archive-2026-10-06.md#file-264003b794ba)保留原样，由[invalid-attempt-methodology.json](invalid-attempt-methodology.json)单独说明方法无效：薄协议客户端复制了 `--loader-managed` 参数却没有执行生产准入/resume 握手，5 条已保存请求均长期等待 strong、未采用 strong/Tail、late Tail 尝试也为 0。该部分失败记录未并入以上 12 次生产 AB 的中位数、均值、PAR-2 或后续正式矩阵。

```powershell
.venv\Scripts\python.exe -m pytest tests/test_qtm_candidates_next.py -k 'pgo_training or real_late_tail' -q -p no:cacheprovider --junitxml=.codex/next-speed/qtm-tail-gates-repro.xml
.venv\Scripts\python.exe tests/benchmark_next_speed_tail.py --binary native/qtm/build/cube_solver_qtm.exe --expansion full-strong --output .codex/next-speed/q2-late-tail-production-repro.json
```

## P1 / P2：支持已补齐，实验未执行

两引擎 `build.ps1` 与 `build_profiled.ps1`已支持 Portable、OutputDirectory、TrainingCases、TrainingTimeout 透传。Portable 使用 `-march=x86-64 -mtune=generic`，普通 O3/LTO 仍是回退。PGO 训练必须正常退出以写出 `.gcda`，没有 profile 文件时拒绝构建，优化阶段以 `-Werror=missing-profile`防止名义 PGO；构建身份包含实际训练集/报告/源码/资产/EXE 散列、编译器与参数。

QTM 的[训练脚本](../../../tests/train_qtm_pgo.py)读取[8 组独立固定打乱](../../../tests/qtm_pgo_cases.json)，默认 `--expansion generic`，训练报告要求原生候选与实际 strong 查询均出现；显式训练 full-strong 时另要求专用展开实际发生。HTM 的[训练脚本](../../../tests/train_htm_pgo.py)读取[自己的 8 组独立固定打乱](../../../tests/htm_pgo_cases.json)，以正常 Python 两阶段候选向原生证明发送单调改进的 incumbent，共享 15 总额度。原 HTM 脚本“身份声明 native_pgo_cases、实际却固定训练 pgo16/known18”已消除。两个脚本显式排除 `initial-1、2、5、8、12、16` 的名称和冻结 Facelets，排除检查通过；本轮并未执行这些训练。

本轮没有执行任一 PGO 训练、PGO 编译或 PGO 性能 AB；脚本/PowerShell 静态语法和训练集检查不能替代这些待执行门禁，因此没有 PGO 采用结论。以下仅为后续命令示例，不是本轮运行记录。

```powershell
& native/htm/build.ps1 -Portable -ProfileGuided -OutputDirectory .codex/next-speed/htm-portable-pgo -TrainingCases tests/htm_pgo_cases.json -TrainingTimeout 5
& native/qtm/build.ps1 -Portable -ProfileGuided -OutputDirectory .codex/next-speed/qtm-portable-pgo -TrainingCases tests/qtm_pgo_cases.json -TrainingTimeout 5
```

P2 本轮没有扩展逆状态下界、任务粒度、新 PDB/Tail 或 GPU 路线。后续只在查询成本、worker 空闲与 Tail 真实命中数据支持新假设时安排独立实验。

## 正式矩阵与保守默认交付

[有效矩阵（归档）](../../evidence-archive-2026-10-06.md#file-d2b4557ffd6f)共 72 条，固定顺序、每条新进程及一次实际页面请求，无方法失败。独立回放 10,641 条公式声明无错误；HTM 严格成功数为 baseline/current 9/10，QTM 为 18/18。HTM PAR-2 均值 34.605111→33.313333 秒（−3.733%），QTM 11.380278→8.909611 秒（−21.710%）。HTM initial-12 配对比 `0.355561/2.770323/3.260260`，QTM initial-2 为 `1.706813/0.469221/1.497900`，均违反重复退化门槛，两个速度方案都不改默认。

[summary-with-bounds.json（归档）](../../evidence-archive-2026-10-06.md#file-f89b30c39b6b)只补齐原始 progress 中的完整层/合法下界/gap，[审计](formal-final/bounds-analysis-audit.json)确认原主指标和门槛完全不变，原 summary 保留。HTM 超时 initial-1 为候选20/下界18/gap2，initial-8、16 为22/18/4。72 条同口径 OS 峰值与逐状态中位数均未超过 5% 增长，无同次配对新增超时；[资源事件审计](formal-final/resource-event-audit.json)确认全部 QTM managed-loader 准入/采用、15 总额度和零照片修正。上述性能仅属于冻结的实验包。

保守默认包位于 `dist/next-speed-2026-10-03-defaults/RubicPhotoSolve`，ZIP 153 文件、2,307,011,998 字节，SHA `af0fba39fdbac43ee8b9c22d7ff57be1f433733a166afe84b33271efe7f446bc`。默认 HTM early off、QTM generic、候选 legacy、late Tail off，保留资源修复；[源码身份](current-defaults-identity.json)、[实际包身份](current-defaults-package-identity.json)和[构建日志](default-package-build.log)单独保存。包内 QTM EXE SHA 为 `68b6e269893fec8ccd10f1d4d86fe4c126e1ab6797459e56ae271579bb9ab0ce`，实际 EXE 的[3 项最终 oracle 门禁](default-native-oracle.xml)通过、0 skip，覆盖默认 generic、显式 full-strong及 1/2/3 额度。

[8 次页面功能检查（归档）](../../evidence-archive-2026-10-06.md#file-26aa80f412da)与[1,107 条公式回放](default-functional/validation.json)通过配置、合法性、照片及布局核对。current HTM initial-1 超时，保留20步合法候选/18下界/2差值，其余七条严格完成；没有覆盖或重算正式性能结论。该包是保守默认和资源修复的本地工作交付，不宣称已通过六状态速度门槛或普遍30秒成功保证。
