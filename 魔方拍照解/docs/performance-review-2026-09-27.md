# 严格最短求解性能审查

审查日期：2026-09-27。审查基线：`1b4d726fb2431ac16c608c3c522fb20e8a588495`。

目标是加快 HTM 严格最短解的证明，保留最短保证。本次检查了 C++ 搜索核心、PDB 与 Tail 数据库、Python 求解和原生进程桥接、服务端任务调度、二阶求解、前端请求流程，以及相关测试与构建脚本。

建议把重构主线确定为：**增强可采纳下界、降低每个候选状态的处理成本、让原生证明更早开始。** 现有 IDA*、三轴下界、常驻 C++ 服务及只读映射表可以继续使用。

本次没有修改现有应用源码或替换 `native/build/cube_solver.exe`。对照实验使用 `.cache/performance-review/` 内的独立源码副本和可执行程序。

## 已测得的收益

本机为 Ryzen 7 9700X，8 核 16 线程，约 32 GB 内存，32 MiB L3。使用现有完整 Corner PDB、完整 Phase-1 PDB、Tail-6 v4；未加载 Edge PDB。

对照版本均由 GCC 16.1.0 使用相同 `-O3 -march=native -mtune=native -flto` 选项重新编译，均未使用 PGO。原型仅改变两处剪枝逻辑：三轴同值加强规则，以及完整大表可用时省略其已覆盖的小剪枝表查询。

| 本次完整证明的最短长度 | 原版中位时间 | 原型中位时间 | 速度提升 | 耗时降低 |
|---|---:|---:|---:|---:|
| 16 步，项目 PGO 训练样本 | 0.133 秒 | 0.072 秒 | 1.84 倍 | 45.8% |
| 17 步，固定随机样本 | 11.754 秒 | 6.748 秒 | 1.74 倍 | 42.6% |
| 18 步，参考序列生成样本 | 29.211 秒 | 15.415 秒 | 1.89 倍 | 47.2% |

每项重复 3 次，使用 16 线程及已经初始化的常驻服务；计时包含 IDA* 各层及正逆方向预选，不含服务启动、Python 前置搜索和浏览器轮询。每个版本输入同一有效候选解，排除上界质量差异。16/17/18 是实际证明的最短长度，不能与打乱序列长度混用。

这些是小规模、本机的对照结果，不能外推为所有随机状态均有相同倍数。测试按版本分组执行，没有锁定 CPU 频率或做硬件性能计数器采样；16 步样本同时也是现有 PGO 训练样本。18 步样本的原版完整证明访问约 3.098 亿个 DFS 节点，原型约 1.864 亿；节点数减少约 39.8%，说明收益并非仅来自时钟波动。

原版及三种原型还交叉求解了 101 个已复原/固定随机状态，返回长度一致，所有解均重新执行验证。现有求解相关测试为 **19 passed**；pytest 仅报告已有缓存目录无法写入的警告。该验证适用于实验筛选，不替代正式合入时对新剪枝规则的系统验证。

## 优先处理的两处剪枝逻辑

**1. 补上三轴同值加强规则。收益已测得，改造成本低。**

位置：[solver.cpp:509](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/src/solver.cpp:509>)。

当前逻辑只取三个 Phase-1 下界的最大值。设它们为 `p0, p1, p2`，可以使用：

```text
axis_lower = max(p0, p1, p2)
if p0 == p1 == p2 and p0 > 0:
    axis_lower = p0 + 1
heuristic = max(axis_lower, corner_lower, other_admissible_lower_bounds)
```

原因是从复原态走第一步后，至少仍位于三个目标子群之一。若总共只走 n 步，该轴到目标子群的距离至多为 n−1；因此三个轴下界同时为 n>0 时，n 步复原不可能。这里比较的是三个独立轴值，不能把混入角块下界的最大值当作轴值；n=0 必须单独处理。

这一规则由 [Kociemba 的最优求解说明](https://kociemba.org/math/optimal.htm) 给出。单独加入规则的初次实验中，17 步样本从 12.114 秒降至 8.223 秒；重复实验中的合并收益见上表。

**2. 根据已加载的完整 PDB 选择查询路径。收益已测得，改造成本低。**

位置：[solver.cpp:513](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/src/solver.cpp:513>)、[pdb.hpp:16](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/include/pdb.hpp:16>)。

当前每个候选先查角排列单表及三个两坐标小表，再查三轴联合表及完整角块表。对于本机加载的完整表：

- 完整 `twist/flip/slice` 联合下界不弱于该轴的 `twist/slice`、`flip/slice`、`twist/flip` 下界。
- 完整角块 PDB 的下界不弱于只看角排列的单表。

小表仍可能作为廉价的提前拒绝器，所以不能只凭数学覆盖关系断言删除必然更快。本次实际对照支持在默认完整大表配置下省略这些查询：单独省略时，17 步样本初次实验从 12.114 秒降至 9.182 秒。

建议在加载表时选择固定搜索路径。缺表或部分覆盖的 PDB 保留原有小表路径；实验原型也保留了这些回退条件。不要在未经覆盖关系验证的配置中统一删除小表。

## 适合作为重构主线的算法升级

**3. 增加带切片内部排列的强联合 PDB。潜在收益高，工程成本较高，尚未在本项目实测。**

位置：[pdb.hpp:14](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/include/pdb.hpp:14>)、[pdb.cpp:618](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/src/pdb.cpp:618>)、[symmetry.cpp:399](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/src/symmetry.cpp:399>)。

现有 Phase-1 状态包含角扭转、棱翻转和四条切片棱的所在位置，却没有区分这四条棱的内部排列。加入 `UDSliceSorted` 后，目标子群更小，距离下界更强；搜索可以在更高层排除更多分支。三轴可以共用同一张表。

一种已有的对称坐标设计约有 3,529,433,088 项：直接按 4 bit 存距离约 1.64 GiB，按 2 bit 存模 3 信息约 0.82 GiB，均不含辅助表。本机的内存规格适合开展这条路线的原型实验。表结构及模 3 距离恢复方法见 [Kociemba 剪枝表说明](https://kociemba.org/math/pruning.htm)。

实施时需新建正确的坐标、转移和共轭规则，尤其要处理对称稳定子；不能只把现有索引乘以 24。建议先实现容易核对的完整距离格式，再衡量压缩方案。当前建表使用原子字节数组和显式 frontier，放大后峰值内存可能远大于最终文件；建表也需要分块、压缩 frontier 或后期反向扫描等改造。

相比增加更多弱投影的查询次数，这条路线直接增强联合约束，更符合深度 18/19 证明的目标。具体收益必须通过项目自己的完整证明样本验证，不能套用其他实现的加速倍数。

**4. 重构候选扩展为分阶段计算，并使用紧凑状态。潜在收益中高，尚未实测。**

位置：[solver.cpp:481](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/src/solver.cpp:481>)、[solver.cpp:311](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/src/solver.cpp:311>)、[solver.hpp:23](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/include/solver.hpp:23>)。

`moved()` 会先计算三个轴全部坐标，然后 `heuristic()` 才按轴提前返回。第一轴已经足以剪枝时，其他轴的转移仍已执行。当前完整 `CubieCube` 虽然已延迟到通过启发式后构造，但每个存活子节点仍更新完整角块/棱块排列与朝向。

建议按“第一轴转移与判界 → 后续轴转移与判界 → 角块判界 → 必要的完整状态”组织热路径，并分别统计各阶段的拒绝率。默认配置可以研究只携带角排列、扭转、翻转、三轴坐标及紧凑棱排列；只有 Tail、可选 Edge PDB、转置表或返回解验证需要时才物化更多信息。

这比单独改 `std::vector` 更接近高频工作。候选排序只在剩余深度至少 12 时启用，因此把它改成固定数组属于后续微调，收益需单独测量。软件预取、SIMD 和表布局优化也应以实测支持，当前没有硬件计数器证据可以把瓶颈完全归因于内存带宽。

## 原生求解入口与任务生命周期

**5. 让 C++ 直接承担短时最优探测，尽早启动证明。收益主要体现于响应时间。**

位置：[server.py:346](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/server.py:346>)。

当前三阶流程是：加载 Python 表 → Python 最优探测最多 0.75 秒 → Python 两阶段最多 1.5 秒 → 创建原生后台任务。原生证明要等前两段完成。

本次逐段实测如下。右侧直接原生求解没有输入已知候选解，使用现有生产 EXE 和热服务，三次测量取中位数。

| 状态 | Python 最优探测 | Python 快速解 | 原生直接严格求解 |
|---|---:|---:|---:|
| 项目 14 步样本 | 0.751 秒，未完成 | 1.518 秒，得到 19 步解 | 0.0097 秒，证明 14 步 |
| 项目 16 步样本 | 0.764 秒，未完成 | 1.516 秒，得到 21 步解 | 0.625 秒，证明 16 步 |

建议采用原生优先的短时探测；难例需要上界时再运行或并行运行快速解生成器，并允许将更好的候选上界传给正在运行的证明任务。并行时应划分 CPU 预算，避免两个搜索都占满处理器。

更短的候选解在恰好达到最优长度时，可以省掉最后一层“找解”；它不能代替对所有更短深度的排除。因而两阶段求解器的提速值得做，但深层证明仍主要依赖更强剪枝。

**6. 修复会意外落入 Python 的路由。代码行为明确，优先级高。**

位置：[server.py:138](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/server.py:138>)、[server.py:152](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/server.py:152>)、[native.py:215](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/cube_app/native.py:215>)。

API 把 `timeout_seconds=null/0/"none"` 解析成无限时，但只有 `timeout_seconds is not None` 才调用原生核心，因此请求无限时反而进入 Python 严格搜索。网页目前会提交有限秒数，默认网页路径不触发这个问题。

另外，`NativeSolverError` 被直接吞掉后静默回退；文件存在性检查也不代表服务已成功加载。建议统一原生的有限/无限时语义，记录并向任务状态暴露实际引擎及回退原因。CPU 调度和超时使用同一绝对 deadline，避免初始化或原生失败后重新获得整段 Python 搜索预算。

**7. 保留常驻进程与已完成的证明工作。收益与用户重试、取消频率相关。**

位置：[native.py:135](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/cube_app/native.py:135>)、[native.py:181](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/cube_app/native.py:181>)、[server.py:71](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/server.py:71>)。

项目已经使用常驻 C++ 服务，不需要重新发明进程池。不过当前取消操作会结束整个服务；下一次请求需要重新初始化坐标表、共轭表及 PDB。实测新进程到 ready 约 0.85–1.17 秒，文件系统缓存状态未严格控制。

建议引入任务 ID 与取消控制消息，保留已加载数据；把坐标转移和对称映射等确定性辅助表版本化缓存。重试相同状态时至少复用“已严格排除到哪个深度”，进一步再研究保存尚未完成的搜索前沿。缓存必须绑定规范化状态、HTM 度量、证明规则版本和已验证的完成状态；一个超时中的深度不能记作已完成。

前端重复点击会取消旧任务并创建新任务，可对相同状态进行去重或复用。服务端 `OPTIMAL_SEARCH_LOCK` 对单用户、单机占满 CPU 的场景是合理保护，不建议直接移除并任意增加重型并发任务。

## 多线程、Tail 与转置表的判断

**8. 保留当前 16 线程默认值，调度优化先补统计。**

位置：[solver.cpp:380](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/src/solver.cpp:380>)。

生产 EXE 在 16 步样本上的三次测量中位数为：1 线程 1.249 秒、4 线程 0.362 秒、8 线程 0.190 秒、16 线程 0.121 秒。本机已有明显的并行收益，不能把“改成多线程”列为尚未实现的主要优化。

当前任务队列受一把互斥锁保护，任务入队/完成会 `notify_all`；分割限制在路径长度小于 7，进入一个较大 DFS 子树后不会继续向空闲线程捐出工作。后续可以统计每线程计算/空闲时间及子树耗时，再决定是否采用工作窃取、可捐出前沿和长期线程池。当前数据不足以声称锁竞争是第一瓶颈。

**9. Tail-7、更多 Edge PDB 和转置表应作为实验配置。**

位置：[tail.cpp:246](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/src/tail.cpp:246>)、[solver.hpp:99](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/native/include/solver.hpp:99>)。

现有 Tail-6 v4 文件实际约 200 MiB，已实现 Bloom 预筛。18 步基准原版访问约 3.098 亿 DFS 节点，只有 54,642 次 Tail 查询，其中 53,277 次由 Bloom 排除。它说明该样本的大量工作发生在抵达 Tail 之前；不能仅因为 Tail 表大就将其认定为主要耗时来源，也不能用查询占比直接代替耗时剖析。

按当前槽位分配，Tail-7 v4 的持久数据约 3.125 GiB，建表还要求至少 10 GiB 可用内存。扩大 Tail 可能有益，但应比较“减少搜索量”与“更多随机查询、建表和内存成本”，本次没有生成大型新表。建议其优先级低于已测得的规则修正和强联合 PDB 原型。

紧凑转置表已经实现，但默认关闭。本次 16 步样本中，单独开启后耗时中位数约 0.224 秒，原版对照约 0.133 秒，DFS 节点基本未减少。默认容量在 16 线程下约占 256 MiB，且随每层 worker 创建而重新分配。若继续研究，宜限制在较高剩余深度，统计命中收益，并保持完整键比较与“子树搜索完成后才写入”的正确性条件。

正逆方向预选已经实现，深层样本确实选择了逆向，建议保留。当前按存活 DFS 节点数选方向，今后可结合实际生成候选数及耗时；预选还依赖候选解长度至少 18，无候选解的难例可以单独研究启用条件。

## 二阶、识别与前端

**10. 二阶改用规范化全状态距离表，收益确定性强。**

位置：[two_by_two.py:132](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/cube_app/two_by_two.py:132>)、[two_by_two.py:170](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/cube_app/two_by_two.py:170>)。

二阶当前使用分离的角排列/扭转下界及 Python IDA*，只在内存缓存首次生成的表。本次 7 步样本首次求解约 1.619 秒，热求解约 1 毫秒，首次等待主要来自建表。该样本不代表所有深层二阶状态都能在 1 毫秒内求解。

与项目“整体转动等价”的定义一致，固定一个角块后状态数为 `7! × 3^6 = 3,674,160`。完整距离按字节约 3.50 MiB，按 4 bit 约 1.75 MiB，辅助转移表另计。离线反向 BFS 后，查询准确距离并逐步选择使距离减少 1 的动作，就能直接输出严格最短解。需要正确还原用户面向对应的动作。类似规范化方式见 [Kociemba 的二阶最优求解器](https://github.com/hkociemba/Rubiks2x2x2-OptimalSolver)。

三阶识别、颜色分配、图像传输和每秒一次轮询影响整体体验，但不参与给定 facelets 后的搜索树。针对本次深层证明目标，它们不应挤占主要重构投入。可以后续把前端轮询改为事件推送，以消除最多约一个轮询周期的结果显示延迟；这不会缩短证明计算本身。后端对首个检测候选的质量计算也有重复调用，但属于识别阶段的小优化。

## 基准和正式重构顺序

现有 [benchmark_solver.py:29](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/tests/benchmark_solver.py:29>) 只调用 Python `OptimalSolver`，两个固定样本也不足以衡量 C++ 深层优化。它不能作为这次重构的主验收工具。

建议按以下顺序交付，每步保留可切换的对照配置：

1. 建立原生基准：区分冷启动、热搜索、端到端时间；收集固定状态、候选解、编译/PDB 版本、超时前完成深度、证明时间和内存峰值。现有 `nodes` 主要记录进入 DFS 的存活节点，须增加全部生成候选数、各 PDB 查询/拒绝次数、每线程工作分布。部分搜索统计只在深度结束后上报，也应在长时间搜索中提供低开销的实时快照。
2. 合入三轴加强及完整表查询路径选择。增加浅层 BFS 对照、已复原态、部分 PDB、取消/超时、不同线程数和正逆方向的回归验证。新 heuristic 必须始终不超过真实最短距离。
3. 修复原生路由并改为原生优先探测；实现保留进程的取消，以及统一 deadline。将网页端的解生成与严格证明时间分别统计。
4. 实验更强联合 PDB，并以分阶段候选扩展为核心重构搜索内核。两条改动分别测量后再组合，避免无法定位收益和退化。
5. 根据负载分布决定是否改任务窃取，再评估 Tail-7、选择性 TT、模 3 压缩及扩展 PGO 训练集。现有 PGO 仅使用一个 16 步候选样本，实际最多搜索到 15 层，未覆盖目标深度 17/18 的证明及方向预选，应加入独立训练集并保留未参与训练的验收集。
6. 二阶全表作为独立小改造交付。

验收集应包含足够多的真实难例和已知/已证明深度 18、19、20 的状态；固定长度随机打乱不等于均匀随机合法状态，也不等于该最短深度。建议同时维护满足朝向与奇偶约束的随机合法状态集合，并报告 p50/p95、超时比例及完成深度，不能只比较成功返回的样本。

## 实验材料

- [全部对照汇总](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/.cache/performance-review/summary.json>)：包含每个样本的 facelets 和打乱序列。
- [原版三次测量与逐层事件](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/.cache/performance-review/confirm_base.json>)、[原型三次测量与逐层事件](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/.cache/performance-review/confirm_tri_lean.json>)。
- [临时原型补丁](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/.cache/performance-review/prototype.patch>)：未应用到现有源码。
- [原生基准脚本](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/.cache/performance-review/audit_benchmark.py>)、[独立原型构建脚本](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/.cache/performance-review/build_variants.py>)。
- [交叉验证与 Python 路径测量](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/.cache/performance-review/validation.json>)、[直接原生/Tail/TT 补充测量](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/.cache/performance-review/additional.json>)、[线程数对照](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/.cache/performance-review/threads.json>)。
- [编译器、提交与文件元数据](<C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解/.cache/performance-review/metadata.json>)。

`.cache/` 实验材料受 Git 忽略；本报告已单独保存在 `docs/`，重构时可把需要长期维护的基准迁入 `tests/`。
