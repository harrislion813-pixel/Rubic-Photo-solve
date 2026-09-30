# QTM 隔离复审修复与短验收

日期：2026-09-30。依据主工作区的 `docs/qtm-isolation-review-2026-09-30.md`，继续在 `codex/htm-rollback-qtm-isolation` 工作树处理，起点为 `b68da78`。主工作区的 README 和审查材料未修改。本轮变更记入 Unreleased；应用版本仍为 1.8.0，未合并到 main，也未重打或覆盖此前的 Windows ZIP。

## 已落实的修复

- **无限期限**：请求只有缺省字段才使用 180 秒；`null / 0 / "0" / "none"` 在 QTM 二阶、三阶、资源排队、原生协议和 Python 回退中保持无限期限。原生协议发送 0，Python 收到 `timeout_seconds=None / deadline=None`。去掉了剩余期限不足时补到 0.1 秒的行为。
- **请求预算**：接纳 HTTP 求解请求后立即计时，HTM 资源让出、二阶求解、探测和后台证明共享绝对 deadline。broker 支持期限和取消，失败时归还 HTM claim；QTM 即使资源空闲也不会接纳已经过期的请求。HTM 响应增加本请求的 `resource_wait_seconds`，避免后台线程随后覆盖全局诊断值。
- **生命周期测试**：异常类、原生可用性判断、mock 路径和 Python 求解测试指向 `cube_app.solvers.htm`；求解测试使用 HTM 私有缓存并在计时前加载表。
- **阶段账本**：分别保留 base、strong、Tail 首次 ready，以及搜索实际采用 strong/Tail 的时间。C++ 只在已有快照采用检查点增加通知，没有改变成本层、坐标或剪枝规则。进度帧携带实际采用的 profile；资产可用 profile 与证明使用 profile 分开保存，候选自己的 profile 随候选保存。
- **候选与清理**：首候选事件唤醒提交请求，后台证明继续。HTTP 首次返回与后续轮询交付候选分别计时。QTM 完整退出和 reader 清理先于 broker 放行下一次请求。
- **wheel**：改为发现 `cube_app*` 子包；CI 在干净 venv 内安装 wheel，使用 `-I` 从源码树外导入两个原生适配器、QTM 后端和 broker。
- **Portable HTM**：普通构建与 PGO 支持通用 x64 模式，CI 和正式打包使用 Portable。打包检查 portable 标记、EXE hash 和当前源码 hash；缺失或过期产物需要重建，`SkipNativeBuild` 时明确失败。

时间字段的含义：`native_search_seconds` 来自原生终态帧，即使超时也尽可能保留；兼容字段 `proof_wall_seconds` 现在同值，不再表示从资源接纳到退出的全部时间，也不能当作纯证明 CPU 时间。`resource_hold_seconds` 包含初始化、搜索、可能的回退和清理；`request_elapsed_seconds` 还包含排队。`native_proof_busy_seconds` 是原生终态帧中 worker busy 的和，保留其原始统计范围，不等同于全进程累计 CPU。加载与搜索可重叠，这些字段不应相加。

## 完整成本层对照

两个状态、每状态每版本 3 次、每次最多 5 秒，15 线程，同资产 hash。QTM 为 portable O3，固定正向、dual off、strong-first，关闭候选和证明缓存、初始上界为空。HTM H0 从 `ae73ca8` 冻结源码单独以同一 Portable 脚本构建，H1 使用隔离源码；12 个源码文件除 Git 换行转换外一致。

另发现 HTM v2 没有关闭证明缓存的参数，诊断现用其已有的 legacy framing，确保三次确实重跑完整层。v2 在排除上界后返回 `no solution found within max depth`，其最后一个完整 progress 帧保存了层数和计数；这是预期的协议行为，不修改 HTM 搜索核心来适配诊断。

| 对照 | 状态 / 排除成本 | 旧版墙钟中位数 | 新版墙钟中位数 | 变化 | 每次总生成量 |
| --- | --- | ---: | ---: | ---: | ---: |
| HTM Portable H0/H1 | pgo16 / 15 | 0.071410 s | 0.065312 s | -8.54% | 10,160,820 |
| HTM Portable H0/H1 | known18 / 16 | 1.198003 s | 1.195982 s | -0.17% | 201,407,415 |
| QTM Q0/Q1 | pgo16 / 17 | 0.015979 s | 0.016059 s | +0.50% | 1,399,731 |
| QTM Q0/Q1 | known18 / 18 | 0.143730 s | 0.142130 s | -1.11% | 13,660,095 |

每组 6 次的完成成本和总生成量一致。并行拆分导致 visited/split 节点和部分查询次数有小幅变化，汇总保留各项范围，**没有声称所有内部计数逐项相等**。QTM 奇偶规则会把不可达的下一成本也记作完成，故 17/18 上界对应 completed_depth 18/19。

这轮同树诊断没有复现旧报告的 +61.2% known18 响应差距；不能据旧的候选开启、找到解即终止的测试认定单位节点吞吐退化。也不能据这两个短层推断任意困难状态或实拍长证明已改善。

## 默认 staged 与资源让出

使用默认 staged 的 initial-1，期限 5 秒，轮询保留所有阶段事件。本轮终态为 timeout，候选 QTM 代价 24、`optimal=false`，完整证明到成本 19；未完成层没有生成证书。最新定点记录：base ready 1.523 秒，首候选 1.610 秒，轮询交付差 0.109 秒，原生搜索 3.438 秒，请求连清理 5.110 秒。此前同一短检查的首候选为 1.531–1.547 秒，原始记录全部保留。

初次 HTTP 提交在 0.75 秒探测预算后可能先返回任务 ID；候选晚于初次返回时由轮询交付，交付差包含客户端轮询等待。5 秒结束前 strong/Tail 均未 ready，实际采用字段保持 null；没有把基础表搜索误报为 strong 搜索。这轮没有测到强表到达后等待长层结束的延迟，尚不能决定是否中断当前层重启。

等待 QTM 完成 ready、确认已进入正常服务后，再提交已预热 HTM 的 R2 请求：HTM 本请求资源等待 **0.062 秒**，QTM 终态 cancelled，进程退出、broker 归零、yield_fault 为 0。这证明该短场景通过 1 秒目标，范围不扩展为所有困难请求的保证。

## 有界复用与单因素消融

复用仅做诊断原型：同一个资源 lease 内连续两次简单请求，20 秒上限、1 GiB 内存检查；生产默认仍为每次请求结束立即释放。立即释放两次均约 1.531 秒；原型首次 1.469 秒、第二次墙钟低于 Windows monotonic 的计时分辨率，原生搜索为 0.000704 秒。观察到的进程峰值约 565.5 MiB，切 HTM 前完整清理额外耗时 0.047 秒。

原型没有验证闲置整整 20 秒时后台 strong/Tail 的内存增长、持续内存上限和多请求代际保护，不能作为可上线复用策略。当前源码已解决立即清理的放行顺序问题；后续若实现复用，仍须完成 idle 期间的内存控制及 HTM 抢占，而非仅延迟退出。

在相同 binary、资产、线程与完整层上，各只切一个因素，每状态 3 次：

| 切换项（相对正向 / dual off / strong-first） | pgo16 中位数变化 | known18 中位数变化 |
| --- | ---: | ---: |
| bounded 方向探测 | +58.68% | +6.51% |
| root dual | -1.83% | -0.55% |
| legacy PDB 查询顺序 | +47.57% | +54.65% |

短状态的探测开销可见，root dual 的差异不足以支持默认变更，strong-first 已有收益。没有据两状态关闭生产方向策略，也没有修改冗余 slice 更新或扩大 dual 热路径；更深状态、候选开启和不同快照下的收益尚未测量。本轮 C++ 搜索改动仅为快照采用通知。

## 验证与可复现产物

最终代码的 43 项受影响 Python/原生/HTTP 测试通过，原始测试报告为 [isolation-targeted-tests-review.xml](benchmarks/isolation-targeted-tests-review.xml)。Ruff、Python 编译、PowerShell 语法解析和版本一致性通过。HTM/QTMStrong 打包预检分别核验 7/19 项；这里只是预检，不是新 Windows ZIP 的验收。最终 wheel 包含 20 个 `cube_app/solvers/` 条目，并通过独立安装导入。

- 汇总：[qtm-isolation-review-summary.json](benchmarks/qtm-isolation-review-summary.json)。
- 完整层：`benchmarks/htm-{h0,h1}-portable-review.json`、`benchmarks/qtm-{q0,q1}-fixed-layer-review.json`。
- HTM 来源：[htm-portable-source-audit.json](benchmarks/htm-portable-source-audit.json)，包含构建参数与冻结/工作树 hash。
- 新版原生构建：`benchmarks/htm-portable-build-review.json`、`benchmarks/qtm-portable-build-review.json`，保留 Portable 编译参数、EXE 与源码 hash。
- 默认 staged 与 ready 后抢占：[qtm-staged-preemption-ready-review.json](benchmarks/qtm-staged-preemption-ready-review.json)。早期生命周期、计时与抢占记录同样保留。
- 两次请求复用原型：[qtm-staged-lifecycle-review.json](benchmarks/qtm-staged-lifecycle-review.json)。
- 消融：`benchmarks/qtm-direction-bounded-review.json`、`qtm-dual-root-review.json`、`qtm-query-order-legacy-review.json`。
- wheel：[isolation-wheel-install-review.json](benchmarks/isolation-wheel-install-review.json)，记录最终 wheel SHA-256 与安装位置。
- 脚本：`tests/benchmark_isolation_short.py`、`verify_htm_portable.py`、`check_staged_isolation.py`、`check_wheel_install.py`、`summarize_isolation_review.py`；回归在 `test_isolation_contract.py` 等受影响测试中。

下一项仍是实现并验证完整的有界复用策略，以及取得 strong_ready→strong_adopted 的默认配置证据。确认强表就绪后困难证明仍由树规模主导，才进入互补 PDB；本轮没有达到这项前置条件，因此未新建 PDB 或加入困难样本。QTM 继续保持实验状态。没有运行旧 48+32 集合、180 秒实拍复测或完整测试套件，也未用短结果替换此前最终 ZIP 的长验收结论。
