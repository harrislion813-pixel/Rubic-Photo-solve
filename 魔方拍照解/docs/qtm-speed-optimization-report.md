# QTM 小规模提速实施与验收报告

日期：2026-09-30。执行 `ai-qtm-speed-optimization-plan-2026-09-30.md`，起点为已阅读的最新 `htm-qtm-isolation-followup-report.md` 所述工作树实际文件。

本轮确认了安全热复用的明显收益，并完成 staged loader 额度、内存接纳、暂停与代际管理。**首次困难请求的严格证明提速、完整 strong 热层提速均未达标。** 最终默认热层比冻结基线慢约 6%；strong 重启、slice 省略和有效预取均未取得足以启用的墙钟收益。这是供审阅的 1.9.0 候选包，不将它描述为已达到整体提速目标的发布版本。

## 1. 实际基线、源码与包身份

实施目录始终是：

`C:/Users/harriron/.codex/worktrees/htm-rollback-qtm-isolation/Rubic-Photo-solve/魔方拍照解`

主目录仍为旧源码，没有在主目录实施修改，没有提交、合并或远程发布。原有未提交的复审修复与报告保留；无限期限、候选通知、阶段账本、清理顺序与 wheel 的既有修复没有另起一套实现。

HEAD 为 `b68da781fd3c2296e9aad0f9496c5786b6b834c5`，**它仅标识祖先提交**。本轮开始前冻结了实际 234 个文件、二进制 Git 补丁、HTM/QTM EXE 和 build-info，以及 22 项资产/缓存/构建文件散列：

- [基线冻结清单](benchmarks/qtm-speed-baseline-freeze.json)，快照位于 `.cache/qtm-speed-baseline/`。
- 初始补丁 SHA-256：`80014568171612bfef4a9154099da97030c3d0fa87aafe3042e79f82dfa6bdc6`。
- 初始 QTM EXE SHA-256：`65828ce5ecba61402351510f8dbb658e32c9b8c93d3c0997ee3a941b8ae5850d`。
- [最终冻结清单](benchmarks/qtm-speed-final-freeze.json)，快照位于 `.cache/qtm-speed-final/`；包含最终实际文件、补丁、构建文件、全部原有资产身份及包身份。
- 最终 QTM EXE SHA-256：`b3e2a755a77caf96a8a55f9ef15bbd444d44506a3dac6a2cfb16d258c8cc2d28`。

最终包为 `dist/QtmStrong-1.9.0/RubicPhotoSolve-1.9.0-QtmStrong-windows-x64.zip`，2,306,980,881 字节、151 个归档项，SHA-256 为：

`a3b6c8fa7a58e46a72d08a10536c61cd560b102aa295cffe058980153eb8a6db`

该 ZIP **仅构建一次**，独立解压至 `.cache/qtm-speed-package-acceptance/RubicPhotoSolve/`，启动解压后的实际 EXE 验收。新清单含 21 个原生/资产/缓存文件的身份、两引擎完整 build-info 和 42 个应用源码散列；逐项验证与当前实现一致。HTM 原生源码、HTM EXE、全部原有资产/缓存散列与冻结基线一致。QTM 为通用 x64 Portable、O3/LTO、非 PGO 构建。旧 1.8.0 ZIP 未用作最新实现的验收证据。

## 2. S0：有效完整层基线

固定为同一组资产、15 线程、eager 就绪后搜索、关闭原生候选与证明缓存、正向搜索、节点 dual off、strong-first。根始终保留 `max(h(s), h(s⁻¹))`。pgo16 配置成本上限 19，使单次完整排除落在约 1.35 秒；known18 配置上限 18，**没有使用会找到成本 20 解的上限 20**。

每配置每状态三次，单次预算 5 秒，全部完整排除且无解/超时。以下为客户端搜索墙钟中位数；原生 elapsed、节点、查询及完整帧另存原始 JSON。

| 状态 | 请求成本上限 | 冻结墙钟中位数 | 最终默认中位数 | 最终变化 | 两版本生成候选数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| pgo16 | 19 | 1.350819 s | 1.431589 s | +5.98% | 125,074,875 |
| known18 | 18 | 0.147569 s | 0.155819 s | +5.59% | 13,660,095 |

原生 `completed_depth` 分别为 20/19，是完整已搜索层加上 QTM 奇偶性直接排除的相邻不可能成本；没有把未搜索的可能层算为完成。生成量精确相同，任务切分、节点和部分查询计数有调度差异。

最终 pgo16 成本 17 的浅回归中位数 0.016901 s；此前报告的 0.016059 s 仅作历史参考，不充当本轮重新冻结的同场对照。最终热层测量有轻量回归测试并行干扰，不能据此精确归因 6% 的变化，但结果不满足提速门槛，且两例超过 5% 退化警戒线。没有以节点变化或噪声解释为收益，也没有追加长测试图翻转结果。

证据：[冻结完整层（归档）](evidence-archive-2026-10-06.md#file-0f82cb0881e6)、[最终完整层（归档）](evidence-archive-2026-10-06.md#file-35eb566890ca)、[浅回归](benchmarks/qtm-speed-final-short-layer.json)。

## 3. S1：staged 强表采用与加载额度

加载控制器将验证工作切成检查点，strong 的对称表、checksum/范围/max 校验和 Tail checksum 均可确认暂停；保留完整校验及文件格式。进入每个加载阶段前发送 `loader_stage`，Python 检查已映射工作集、private bytes、待映射字节和系统可用内存，接纳后才恢复。默认 loader 4 线程，从 15 个总额度中扣除；候选活跃时证明 10 线程，候选退出后 11，loader 完成后可在安全派发点恢复到 15。服务帧区分实际执行 loader 数与保留额度。

独立实现一次性 strong 升级重启：低频检查 ready，停止并完整回收当前层 worker，从同一根和同一成本重新开始；保留绝对 deadline，重算正逆根下界并取 max。中断层不产出证书，Tail 仍仅在完整层边界采用。控制了“一次重启、剩余预算至少 0.5 秒、已搜索至少 0.1 秒”的试验门槛。

initial-1 基线和变体各运行一次 15 秒：

| 指标 | 冻结 dirty 基线 | shared loader + restart 变体 |
| --- | ---: | ---: |
| base/startup | 1.487 s | 1.526 s |
| 原生候选进入后台 | 1.536 s | 1.550 s |
| strong ready | 8.961 s | 9.038 s |
| strong adopted | 无 | 9.305 s |
| ready→adopted | 无 | 0.268 s |
| Tail ready / adopted | 9.472 s / 无 | 9.494 s / 无 |
| 完整排除成本 | ≤19 | ≤19 |
| 请求终态 | timeout | timeout |

变体在成本 20 重启一次，丢弃该未完成层 486,934,422 个生成候选；worker 停止 0.000119 s，中断层耗时 6.372 s，采用时 deadline 剩余 5.695 s。采用 strong 的快照 ID `2120499397680`，后来的 Tail 快照 `2119941200080` 未进入该层。旧试验帧中 profile 文案仍为 base，但 `strong=true`、快照 ID 和 718,915,787 次 strong 查询证实有效采用；最终 EXE 已将 ready 阶段文案修为 `strong-no-tail`。

这是**机制有效但性能未过门槛**：完成成本没有提高，丢弃工作很大，不把首次采用等同于首次严格证明加速。重启开关保留，默认仍 `boundary`。加载额度与完整校验控制默认启用；由于此对照同时加入额度与重启，不能将性能差异归因到 loader 线程数。本轮未额外展开线程数消融。

证据：[staged 基线（归档）](evidence-archive-2026-10-06.md#file-aec7e85af74c)、[staged 重启变体及全部帧（归档）](evidence-archive-2026-10-06.md#file-8c5edb579b5e)。这些脚本 50 ms 轮询的交付时间没有代替生产页面指标。

## 4. S2：完整 strong 热路径独立消融

省略 slice 仅在 QTM、完整 strong、strong-first、无需 small Phase-1 时有效；省去主轴及两辅助轴的 slice-combination 转移，保留角/朝向、sorted slice、materialize 和接受后递归需要的字段。base 与 partial Phase-1 不走省略路径。分别记录 `slice_updates` 与 `slice_updates_skipped`。

预取先修复有效 strong-first 路径：`prepare_index → prefetch → load_distance`，记录 `strong_prefetches`。on 的计数实际非零，off 为零，未再测试无效开关。

两个实验分别使用同一 EXE（`9ac80e683bfa3c5311deb74f4f6bbec14db2fc7bac64a5f85977aa05b3753179`）、同资产、两个 eager service，按 AB/BA 交错，每状态每变体三次。每对生成量精确相同。该实验二进制早于最终 ready 文案/控制器收尾构建；同实验内部未混用二进制。

| 独立开关 | pgo16 墙钟变化 | known18 墙钟变化 | 决策 |
| --- | ---: | ---: | --- |
| strong-slice omit | -0.42% | -0.01% | 无稳定 ≥5% 收益；默认 keep |
| pdb-prefetch on | +0.30% | -0.02% | 无稳定墙钟收益；默认 off |

没有合并两个变体掩盖单项收益，也没有继续扩大试验。最终 EXE 的独立四分之一转 BFS oracle 深度 3 检查 1,195 状态，所有 cutoff 0..30 对比 keep/omit 的合法下界和接受后 materialize，通过。实现期间还检查了 base/partial Phase-1 的后备路径；最终可重放记录为完整 strong oracle。

证据：[slice 消融（归档）](evidence-archive-2026-10-06.md#file-940b73f11bb7)、[有效预取消融（归档）](evidence-archive-2026-10-06.md#file-621fc7f09108)、[最终 oracle](benchmarks/qtm-speed-final-oracle.json)。

## 5. S3：有界复用、内存与 HTM 优先

CPU lease 和 resident 登记分离；单服务控制器串行请求与退出，常驻 dispatcher 处理 idle 期间的服务事件。generation 与请求 ID 分开，idle epoch 防止旧 TTL 关闭新请求。请求结束后 loader 已完成或收到暂停确认才进入 idle；确认失败、故障、取消、配置身份变化或内存不足时立即退出。重新启动仍完整校验，不以 mtime/size/manifest 替代校验。

本机内存约 31.15 GiB，冻结策略为：单 resident、TTL 20 秒、base idle 1 GiB、strong idle 8 GiB、系统空闲保留 2 GiB；每 250 ms 采样工作集/private/系统可用内存，并覆盖 busy/idle。8 GiB 为包含约 3.76 GiB 完整映射工作集的保守接纳上限，不是声称程序需要 8 GiB。内存不足拒绝新阶段，不主动预热。

每生命周期场景一次，不启动深层证明：

| 场景 | 实测结果 |
| --- | --- |
| 两个不同浅状态 R2 → F2 | 首次 wall 1.997038 s/startup 1.470100 s；第二次 wall 0.004665 s/startup 0.001165 s，初始化减少 99.92%；同进程代际，旧 idle epoch 无效 |
| 未完成 loader 的完整 TTL | 实际等待 20.169 s；暂停后工作集峰值 567.47 MiB，private 36.43 MiB，可用内存最低约 17.09 GiB；到期进程/reader/resident 清理完成 |
| 完整 strong/Tail 的完整 TTL | 实际等待 20.469 s；工作集峰值 3.760 GiB，private 42.84 MiB，可用内存最低约 13.87 GiB；到期释放 |
| strong idle → 已预热 HTM | HTM 资源等待 0.326 s，完整清理后才授予 HTM |
| busy 且 loader 活跃 → HTM | 浅请求 ready 屏障，HTM 等待 0.045 s；没有借深层搜索制造场景 |
| 内存越界 | 将活动保留上限注入为 100 MiB，监视器执行真实进程驱逐 |
| 故障及旧代际 | kill 后重新创建进程；旧 generation 驱逐不能操作新进程 |

最终 broker 无 QTM active/resident、无 HTM holder、yield_faults=0。自动 TTL 清理中间记录可能先看到 `_process=None`、resident 回调尚在收尾；验收屏障等待 resident 也清空。HTM 准入始终等待完整退出/reader 清理；增加了关闭阶段诊断，失败清理不会提前授予 CPU。

复用满足该机器的小规模门槛，默认 `bounded`，独立回退 `CUBE_QTM_REUSE=off`。此结论限于两个浅状态、实测 TTL 和抢占场景，未外推困难状态严格最短收益或总体成功率。

证据：[生命周期原始事件、内存样本与 broker](benchmarks/qtm-speed-reuse-lifecycle.json)。

## 6. 新包两状态生产页面验收

默认 staged、完整原有资产、每状态仅一次 30 秒。通过浏览器操作实际解压后的 1.9.0 页面，页面原有约一秒轮询。为避免冻结 EXE 控制台日志缓冲，采集脚本在 loopback relay 记录生产页面本身的请求/响应，不附加任何运行中 job 轮询；只在终态后读取账本和核验候选。表中响应时间从 relay 收到页面 POST 起算，是实际页面流量交付指标；DOM 观察有几十毫秒后续观察延迟，另外保存。

| 状态 | cold/warm | 后台首候选 | 页面候选响应 | DOM 首候选观察 | 页面终态响应 | 完成成本 | 候选成本 / 已证下界 / 差值 | 严格最短 |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| initial-1 | cold | 1.594 s | 1.810 s | 1.903 s | 30.363 s | ≤19 | 24 / 20 / 4 | 未证明 |
| initial-12 | cold | 1.515 s | 1.785 s | 1.829 s | 30.366 s | ≤19 | 24 / 20 / 4 | 未证明 |

initial-1：startup 1.562 s，strong/Tail ready 9.172/9.641 s，生成 2,653,433,330 候选，工作集峰值 3.763 GiB。ready 快照分别为 `2210200350160` / `2210771458928`。

initial-12：startup 1.515 s，strong/Tail ready 9.031/9.500 s，生成 2,686,175,361 候选，工作集峰值 3.762 GiB。ready 快照分别为 `2775673578272` / `2776247447088`。

**两例默认 boundary 都未采用 strong/Tail；实际搜索 profile 仍为 base。** 两例后台搜索 wall 分别 28.422/28.482 s，不等同纯证明 CPU；deadline 均保持原请求 30 秒。两请求之间超过 20 秒 TTL，所以第二例也是 cold，没有用它冒充 warm 复用验收。结束后 resident 正确为 IDLE，HTM R2 实际准入回收等待 0.359 s，HTM 解成本 1 且严格最短。

两组各六张原照片只走一次识别校验，检测/颜色分类生成的 facelets 与冻结参考一致；候选均用独立 cubie 重放、QTM 成本重算，页面动作文本一致，候选没有继承 optimal=true。

新包 initial-12 最终页面状态标记截图：

![新包页面显示候选可执行、严格最短尚未证明](benchmarks/qtm-speed-package-page.jpg)

冻结 dirty 基线的 initial-1/12 页面也各运行了一次 30 秒，均有成本 24 的有效候选、排除到 19、未证明严格最短。但辅助脚本日志缓冲/观察结束采集失败，缺失完整 HTTP 账本；首候选观察分别 3.091/2.071 s，终态观察过晚，均只能视为上界。保留原始失败和观察证据，**不用于跨版本页面提速比较，不重复这两次长请求**。

证据：[新包实际页面账本与传输记录（归档）](evidence-archive-2026-10-06.md#file-3f752c5ab7ac)、[两组照片识别](benchmarks/qtm-speed-package-photo-acceptance.json)、[冻结基线页面观察与候选重放](benchmarks/qtm-speed-baseline-page-observations.json)。

## 7. 生产参数、停止项与验证边界

| 机制 | 当前默认 | 独立试验/回退 |
| --- | --- | --- |
| 资产加载 | staged，loader 4，与候选/证明共享 15 总额度 | `CUBE_QTM_LOADER_THREADS`、`CUBE_QTM_LOADER_BUDGET=shared/independent`；原生无 managed loader 为诊断旧路径 |
| strong 升级 | boundary | `CUBE_QTM_STRONG_UPGRADE=restart`（至多一次，deadline 不变） |
| slice 转移 | keep | `CUBE_QTM_STRONG_SLICE=omit`，仅完整 strong 合法路径 |
| strong-first 预取 | off | `CUBE_QTM_PREFETCH=on`，有真实执行计数 |
| resident | bounded，20 秒，单进程 | `CUBE_QTM_REUSE=off` |
| 内存 | base 1 GiB / strong 8 GiB / 保留 2 GiB | `CUBE_QTM_BASE_IDLE_BYTES` / `CUBE_QTM_STRONG_IDLE_BYTES` / `CUBE_QTM_MEMORY_RESERVE_BYTES` |
| 根下界 / 节点 dual | 根正逆 max 保留；节点 dual off | 未重复 root/off 空消融；selective dual 未启用 |
| 方向选择 | 既有策略保留，与根 max 分开 | S4 未展开新方向策略；不针对 facelets 特例 |

S4/S5 未继续：S1 重启没有提高完成层，S2 两项墙钟收益不足，最终热层还有退化；按停止条件结束扩大实验。没有新增 PDB、扩大 Tail、全层 TT、工作窃取或新增 selective dual，也没有恢复 48+32、全实拍或 180 秒重复长测。

43 项针对性 pytest 通过，覆盖有界复用/内存接纳/暂停失败/代际与 epoch/HTM 准入、已有无限期限/候选通知/请求预算/清理次序与版本；变更文件 Ruff、compileall 通过。最终原生 oracle 通过，独立解压包 21 文件验证、42 源码散列对齐、两状态页面及候选重放、12 张照片参考校验均通过。wheel 只沿用既有实现检查所需的元数据构建，不把中途 wheel 当作最终交付包。

采集辅助脚本的首次错误记录仍保留：staged 新协议帧识别、TTL 收尾屏障、基线页面日志缓冲，以及新包开始任何求解前的采集器替换。它们不计作额外性能样本；新包两状态没有补跑。最终候选 ZIP 通过功能与隔离验收，**热证明性能及默认 staged 强表及时采用的目标仍未满足，后续推广应保留这一限制**。

数据总览：[qtm-speed-summary.json](benchmarks/qtm-speed-summary.json)；针对性测试：[qtm-speed-contract-tests.xml](benchmarks/qtm-speed-contract-tests.xml)；构建：[qtm-speed-package-build.log](benchmarks/qtm-speed-package-build.log)。
