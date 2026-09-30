# HTM 恢复与 QTM 隔离后的项目复审

日期：2026-09-30。审查对象：实施分支 `codex/htm-rollback-qtm-isolation`，提交 `b68da781fd3c2296e9aad0f9496c5786b6b834c5`，版本 1.8.0。

实施工作树：`C:/Users/harriron/.codex/worktrees/htm-rollback-qtm-isolation/Rubic-Photo-solve/魔方拍照解`。当前主目录仍是 `c01d90d` / 1.7.1，两者没有合并。本次在主目录保存复审意见，没有修改实施分支的生产代码、重新构建原生程序或重复长求解。

主要依据：[实施报告](C:/Users/harriron/.codex/worktrees/htm-rollback-qtm-isolation/Rubic-Photo-solve/魔方拍照解/docs/htm-rollback-qtm-isolation-report.md)、[原实施方案](ai-htm-rollback-qtm-isolation-plan.md)、源码、最终包原始运行记录及定点短检查。此前的 [1.7.1 优化建议](qtm-optimization-review-2026-09-30.md)作为历史分析保留；下一轮以本文的优先级为准。

## 1. 总体判断

恢复与隔离的主要结构已经落地：HTM 来源为 1.4.0，QTM 来源为冻结 1.7.1，分别拥有原生源码、EXE、进程、资产、缓存和 Python 回退；默认稳定包明确为 HtmFull，QtmStrong 单独提供。报告中的 HTM 精简验收通过，有来源审计与最终 ZIP 实跑记录支持。

QTM 功能迁移和基本隔离已有证据，但性能、请求契约和测试迁移仍有缺口。应继续保持实验状态。下一轮优先处理接入与测量，再判断算法投入；现有材料不足以把隔离后的响应变慢认定为搜索内核的单位节点吞吐退化。

## 2. 已确认的问题

### 2.1 高优先级：QTM 无限时请求被改成 180 秒

[server.py:478](C:/Users/harriron/.codex/worktrees/htm-rollback-qtm-isolation/Rubic-Photo-solve/魔方拍照解/server.py:478) 将 `None / 0 / "none"` 解析为无限期限后，又通过 `timeout_seconds or 180` 传给 QTM。QTM 后端也将 timeout 声明为非空数值并直接计算 deadline。

本次用模拟后端调用 HTTP 处理器，三种无限时别名最终传入的值均为 180。HTM 保留无限期限，因此同一 API 契约在两种 metric 下不一致。困难状态可能在用户明确选择无限时后被提前终止。

建议：将 `float | None` 贯穿 QTM 二阶、三阶、排队与原生调用，只有请求未提供字段时采用默认值。添加三个别名的轻量 API 回归，核对 deadline 为 None。

另外，HTM 的 `BROKER.enter_htm()` 在请求计时与 deadline 创建之前调用（server.py:484、497）；资源让出等待未计入用户预算。修正时应从请求接纳开始创建绝对 deadline，传递剩余预算。

### 2.2 高优先级：生命周期测试没有完成模块迁移

[tests/test_search_lifecycle.py:13](C:/Users/harriron/.codex/worktrees/htm-rollback-qtm-isolation/Rubic-Photo-solve/魔方拍照解/tests/test_search_lifecycle.py:13) 仍从旧 `cube_app.native` 导入异常类，服务器已经捕获 `cube_app.solvers.htm.native` 中的另一组类。

本次定点运行，**2 项失败，耗时 0.28 秒**：

- `test_native_failure_uses_remaining_budget_and_exposes_reason`：模拟原生故障没有触发 Python 回退。
- `test_native_timeout_does_not_restart_in_python`：预期 timeout，实际 error。

这是测试引用陈旧导致的失败，不能据此认定真实隔离 HTM 抛出的异常也处理错误。但 CI 的常规 pytest 任务包含这些测试，因此发布前必须修复测试导入，并检查其他仍绑定旧模块的模拟与可用性判断。

复现：在实施工作树运行 `python -m pytest -q tests/test_search_lifecycle.py::test_native_failure_uses_remaining_budget_and_exposes_reason tests/test_search_lifecycle.py::test_native_timeout_does_not_restart_in_python -p no:cacheprovider`。

### 2.3 中优先级：时间账本会混淆强表、Tail 与证明搜索

[QTM 原生适配器:338](C:/Users/harriron/.codex/worktrees/htm-rollback-qtm-isolation/Rubic-Photo-solve/魔方拍照解/cube_app/solvers/qtm/native.py:338) 对每个 `asset_ready` 都覆盖 `strong_ready_elapsed_seconds`；[QTM 后端:149](C:/Users/harriron/.codex/worktrees/htm-rollback-qtm-isolation/Rubic-Photo-solve/魔方拍照解/cube_app/solvers/qtm/backend.py:149) 也没有按 stage 区分。模拟 strong 在第 1 秒、Tail 在第 2 秒到达后，最终 strong 时间记录为第 2 秒。

后端的 `proof_wall_seconds` 从资源获准开始计时，包含进程启动、资产加载、候选以及可能的 Python 回退；它不是纯证明搜索时间。实际记录如下：

| Q1 实拍 | 强表 ready | 首候选 | 当前 proof_wall_seconds | 原生 result.elapsed_seconds |
| --- | ---: | ---: | ---: | ---: |
| initial-1 | 8.968 s | 9.000 s | 28.281 s | 19.315 s |
| initial-12 | 8.734 s | 8.765 s | 18.656 s | 9.917 s |

建议分别记录 base/strong/Tail 的首次 ready、搜索实际采用快照的时间、原生搜索时间、资源占有总时间和请求总时间。不要简单相加可能重叠的 staged 加载与搜索阶段。

### 2.4 中优先级：wheel 遗漏新的求解器子包

[pyproject.toml:28](C:/Users/harriron/.codex/worktrees/htm-rollback-qtm-isolation/Rubic-Photo-solve/魔方拍照解/pyproject.toml:28) 仍固定 `packages = ["cube_app"]`。本次在临时目录构建 1.8.0 wheel，归档中 `cube_app/solvers/` 条目为 0，因此安装 wheel 后无法导入新增求解器。

此问题针对 wheel / 普通 pip 安装；不能据此否定已从源码打包并实跑的 Windows ZIP。建议改为发现 `cube_app*` 子包，并增加隔离环境中的安装后导入检查。

### 2.5 发布前补齐：HTM 二进制仍依赖构建机 CPU

[native/htm/build.ps1:51](C:/Users/harriron/.codex/worktrees/htm-rollback-qtm-isolation/Rubic-Photo-solve/魔方拍照解/native/htm/build.ps1:51) 固定使用 `-march=native -mtune=native`；QTM 已有 Portable 选项。CI 的 HTM 构建使用此脚本。

本机 H0/H1 使用同模式的对照仍有效，但不能由此证明其他 CPU 能运行 HTM ZIP。若交付目标包含其他 x64 机器，应移植 portable 构建开关，并建立同模式的 H0/H1 对照；无需修改 HTM 搜索源码。

## 3. 实施报告中的性能结论需要收窄

### 3.1 known18 短测并未执行方案要求的纯证明诊断

原方案第 5.3 节要求关闭候选和证明缓存。[短测脚本:66](C:/Users/harriron/.codex/worktrees/htm-rollback-qtm-isolation/Rubic-Photo-solve/魔方拍照解/tests/benchmark_isolation_short.py:66) 关闭了证明缓存，却遗漏 `--no-native-candidate`。原始结果确有数百万候选搜索节点和候选改进。

known18 的 QTM 最短代价为 20。复测中完成成本 18 排除时的累计生成量相同（13,660,095），但最终成本 20 找到解就停止，整次运行的搜索工作量不同：

| 版本 | 三次总生成量 | 原生耗时 | 生成量 / 原生耗时的中位数 |
| --- | --- | --- | ---: |
| Q0 | 50.55 / 75.58 / 107.18 百万 | 0.592 / 0.888 / 1.351 s | 85.09 百万/s |
| Q1 | 123.04 / 384.01 / 95.74 百万 | 1.433 / 4.530 / 1.123 s | 85.23 百万/s |

依据：实施工作树 `docs/benchmarks/qtm-{q0,q1}-known15-retest.json`，逐次读取 `result.generated_candidates` 和 `result.elapsed_seconds` 后计算。

这个比值只是辅助诊断，不能代替固定树的吞吐测量。不过它足以说明：报告中 +61.2% 的响应中位数差距，并没有独立证明每个节点处理变慢。候选与并行发现首个解的时机可能影响最后一层；具体原因仍须定点测量。

下一次只运行固定、可完整排除的成本层，关闭候选和证明缓存、冻结方向参数与初始上界。可先用已完成的成本 18，不再把找到解后提前终止的成本 20 总耗时作为固定树比较。保留每状态 3 次、单次最多 5 秒的规模。

### 3.2 实拍测试使用 eager，程序默认使用 staged

最终 Q0/Q1 实拍记录的 `asset_loading` 都是 eager，验收脚本也默认 eager；适配器默认值则为 staged。生命周期脚本同样显式选择了 eager。

因此“首候选约 9 秒”是该 eager 对照的结果，不能直接写成默认程序的首候选表现。默认 staged 下基础表求解、strong 后台到达、实际采用快照，以及请求结束时终止加载，仍缺少对应验收证据。

应补一个短期限的默认配置请求，核对 ready/candidate/cancel/进程释放；不需要重跑两组 180 秒实拍或旧大集合。

### 3.3 重复冷启动解释部分差距，不能解释全部差距

Q0 第二次实拍复用常驻进程；Q1 每个请求后退出原生进程，第二次又支付约 8.7 秒启动成本。它们反映了真实生命周期差异，但不能用来单独比较内核搜索速度。

另一方面，initial-12 的原生搜索时间也从 5.934 秒增至 9.917 秒，initial-1 从 12.198 秒增至 19.315 秒。故不能将端到端退化全部扣在加载上；应先冻结候选、方向和完整成本层再定位剩余差距。

报告诚实保留了 QTM 实验状态及资源让出尚未独立达标的限制，这些结论应保留。

## 4. 下一轮 QTM 优化顺序

| 顺序 | 工作 | 小规模验收 |
| --- | --- | --- |
| 1 | 修无限期限、HTM 计时起点、陈旧测试导入与 stage 时间账本 | 模拟 API、定点生命周期测试；不启动深层证明 |
| 2 | 建立固定完整层诊断，补默认 staged 请求 | 现有 2 个诊断状态；仅受影响项，每次 ≤5 s |
| 3 | 比较“请求结束立即释放”和有上限的短期复用策略 | 简单状态连续两次请求，再切 HTM；记录额外让出时间与内存 |
| 4 | 优化首候选交付与 strong 接入 | 记录 candidate_ready 与 HTTP 返回、strong_ready 与 strong_adopted 的差值 |
| 5 | 再做方向策略、strong 热路径和 dual 成本消融 | 同资产、同编译配置、同完整层；只切换一个因素 |
| 6 | 确认强配置证明仍受搜索树规模限制后，再试互补 PDB | 先证明下界合法、说明内存与初始化代价，再增加最多 2 个困难诊断样本 |

第 3 项不是建议永久占用大表。可以试验 20–60 秒的有界复用，设置内存上限，并在 HTM 到来时立即取消加载与退出 QTM；未使用 QTM 时仍保持零进程。释放资源的完整清理应先于 broker 放行下一次 QTM，或以进程代际保护异步清理，避免旧请求的清理与新进程交错。现有顺序先 release broker、再 release_assets，应在改变复用策略时一并核对。

第 4 项有两个具体切入点：

- 后端目前 `worker.join(min(0.75, timeout))` 只因工作线程结束而提前返回。首候选到达应触发独立事件，使等待中的 HTTP 请求能立即交付候选。
- 原生 strong 快照仍只在成本层边界采用（`native/qtm/src/solver.cpp:1788`）。先测默认 staged 下的接入延迟；若确有长时间等待，再实现受控中断当前层并用新快照重启。保留此前完整层，未完成层不形成证书，绝对 deadline 不重置。

第 5–6 项继续参考旧优化审查中的方向误选、完整 strong 路径上的冗余 slice 更新、便宜 dual 与互补投影思路。路径已迁至 `native/qtm`；这些属于后续实验，当前报告尚未证明哪一项是两组实拍退化的主因。

## 5. 本次检查范围

已完成：读取实施方案与报告、核对隔离源码和 CI/构建配置、分析已有短测与实拍 JSON；运行 2 项定点生命周期测试；模拟无限期限 API 和 strong/Tail 时间事件；在临时目录检查 wheel 内容。

没有运行旧 48+32 集合、长实拍复测、原生重编译或完整测试套件。未修改生产源码，未合并分支或发布。HTM 的既有精简验收结论来源于实施记录；本次额外检查揭示的 CI 与契约问题应在后续交付前解决。
