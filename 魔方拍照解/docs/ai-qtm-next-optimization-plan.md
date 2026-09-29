# QTM 第二轮强优化行动方案

日期：2026-09-29。审查源码：`660988c`（v1.6.2）。本文承接 `qtm-strong-optimization-report.md`，不重做上一轮已经完成的建表与框架工作。

本文最初在方案阶段交付了任务书、已有验收数据再分析和独立坐标微基准；当时生产求解器与资产尚未修改。后续 N0–N7 已实施并完成正式验收，结果和未达到的目标见[QTM 第二轮报告](qtm-next-optimization-report.md)。下面的速度指标是原始实施目标；坐标微基准的倍数不能当作整个求解器的加速。

## 1. 决策与目标

下一步以“减少强表单次查询成本、进一步减少 20/21 步搜索量、降低启动与候选交付等待”为主线。保留强配置，不退回只做低成本修补；同时把强优化投入放到已经有证据的高频路径，而不是继续扩大没有证明收益的资产。

优先顺序：

1. 去掉强表坐标查询中的完整状态构造与动态分配，改为经过等价验证的查表 + XOR。
2. 为 QTM Phase-1/强联合表实现有证明的三轴加强；实现选择性逆状态下界查询和加权 pathmax/BPMX 对照。
3. 实现不依赖已有候选、适配 QTM 奇偶预算的方向选择，替换当前固定深度触发。
4. 将已证实最大距离为 14 的完整强表压为 4-bit 精确距离，改造验证、初始化与分阶段启用。
5. 修正候选生成与 HTTP 交付之间的等待，并让新候选和空闲算力及时进入正在运行的证明。
6. 以当前强配置为基线，在完整难例集与新增未见集验收，不再用相对 v1.5.0 的高倍加速作为主要成绩。

必须交付：N0–N7 的代码、试验和报告。N1、N2 的三轴加强、N3、N4、N5、N6 是实现任务；N2 的 dual/BPMX 必须完成正确原型和消融，是否默认启用由总耗时决定。不能仅完成 N1 的微基准或只优化简单状态就结束。

| 验收项 | 当前依据 | 下一轮目标 |
| --- | --- | --- |
| 公开 48 状态、4 线程、60 秒、3 次的 PAR-2 | 62.827 秒 | ≤45 秒，即兑现上一轮相对 B0 的 2 倍目标 |
| 同一 144 次运行的证明成功数 | 80/144 | ≥108/144；32 个随机状态至少完成 72/96 次 |
| 当前强版与新版都完成的困难状态 | 以当前强版 ≥1 秒为纳入条件 | 配对耗时比几何平均 ≥2 倍，至少 10 状态；保留全部超时统计 |
| 相同完整排除预算、关闭候选的搜索量 | 固定 18/19 层及选定 20/21 层 | 剪枝组合的生成候选数几何平均减少 ≥2 倍；N1 单独不应改变搜索树 |
| 强表距离存储 | 3,529,433,088 byte | 1,764,716,544 byte，精确值逐项一致 |
| 强配置峰值工作集 | 5.09 GiB | 目标 ≤4 GiB；实际测量，不能只减文件大小推算 |
| 新进程、热文件缓存下初始化 | 中位 5.23 秒 | 中位 ≤2 秒；单列真正冷文件缓存条件 |
| 热 HTTP 首候选 p95 | 1.00 秒，包含交付等待 | ≤0.5 秒；首次冷请求候选 p95 目标 ≤2 秒 |
| 3 秒 QTM 候选质量 | 32 状态代价中位 25 | 中位 ≤24，且缺失候选不增加；核心证明对照仍固定候选条件 |
| HTM 与已有简单 QTM 回归 | 上轮记录 | 代表性耗时回退 ≤10%，短于 10 ms 的测量另批量计时 |

上述目标未达到时，保留原始结果并继续分析或明确报告未完成。公开 25/26 步极端状态仍需纳入固定指标，但不承诺全部在 60 秒内证明。

## 2. 本轮审查的新证据

### 2.1 上轮成果与真正剩余样本

完整 QTM Corner、Phase-1、两组 Edge、三轴强联合 PDB、Tail-7/8、原生候选器与跨预算层 worker pool 都已落地，复用这些产物。上一轮的 104.0 倍配对耗时提升来自另一个中深度补充集；它说明此前缺少 QTM 强下界的问题已明显改善，不能外推到独立随机难例。

重新读取并核对公开验收原始文件 SHA-256 后：

- 32 个随机状态共 96 次运行，只完成 44 次证明。
- 14 个状态三次都超时；6 个状态只有部分重复完成；12 个状态三次均完成。
- 超时随机状态多已排除至 19 或 20，当前正在搜索 20 或 21。这里的 `completed_depth` 含奇偶性证明，不能一律解释为实际遍历了该数值的层。
- 这 96 次运行全部 `inverse_direction=false`；原始条件未预给候选且关闭动态候选。
- 合计生成约 591.61 亿候选，查询 Phase-1 约 1286.77 亿次、强表约 **417.21 亿次**；Tail 只查询 113,493 次、命中 44 次。
- 当前 worker idle 很低，生成量负载比 p95 约 1.07。现有数据没有把工作窃取或更多线程指向第一瓶颈。

这说明首先应该改善大量失败分支的计算与剪枝，而不是只改善找到最终公式时的末段。

### 2.2 找到了强表坐标热路径中的具体开销

当前路径：

```text
StrongPatternDatabase::distance
  → SortedSliceSymmetry::canonical_index
  → SortedSliceSymmetry::flip_conjugate
  → cube_from_sorted_slice
  → unrank_permutation（多个 std::vector）
  → cube_from_flip / conjugate_edges / flip_coord
```

定位：`native/src/strong_coords.cpp` 的 `flip_conjugate/canonical_index`，`native/src/cube.cpp` 的 `unrank_permutation`。这些运算发生在每次强表查询中，并非只发生于初始化。

根据 `Phase1Symmetry::conjugate_edges` 的位变换公式，对固定对称映射 `y`，翻转变换可分成“原 flip 的线性位置变换”和“由 sorted-slice 决定的固定偏移”：

```text
F(f, s, y) = L_y(f) XOR K(s, y)

L_y(f) = phase1.flip_conjugate(f, y)
K(s,y) = slow_flip_conjugate(0,s,y) XOR phase1.flip_conjugate(0,y)
```

`s` 是 11,880 种 sorted-slice 坐标；`f` 是 2,048 种 flip；`y` 是 16 种对称映射。相同 `s,y` 的偏移只需初始化一次。

本轮已在独立程序中验证：全部 `s×y` 的零向量与 11 个基向量，加上 1,048,576 个坐标样本，共 3,329,536 次对照无差异。额外偏移表仅 380,160 byte。相同 portable O3/LTO 编译、每轮 4,194,304 次索引计算、两种路径交替各三轮：

| 路径 | 中位秒数 | 范围 |
| --- | ---: | --- |
| 当前完整构造路径 | 0.617850 | 仅坐标计算 |
| 查表 + XOR 原型 | 0.0051034 | 仅坐标计算 |

这是约 **121.1 倍的坐标微基准比值**，未包含 PDB 随机读取、DFS、线程竞争和候选生成，不能宣称整体求解加速 121 倍。它足以把 N1 排到最高优先级；完整求解收益必须另测。

证据：[分析 JSON](benchmarks/qtm-next-optimization-analysis-2026-09-29.json)、[可复现微基准源码](benchmarks/qtm-round2-coordinate-probe.cpp)。

### 2.3 还有三类明确的接入缺口

1. `solver.cpp:1240` 对 QTM Phase-1 显式关闭 `strengthen_axes`，强表路径也只取三轴最大值，没有相等加强。需要重新证明并补上，而非以 HTM 开关名称推断已经启用。
2. `solver.cpp:1255` 的方向探测要求初始 incumbent 代价 ≥18，并把探测层设在 16 附近；无初始候选时不启用，部分奇偶预算序列也不会访问该层。动态候选到达后这项决定不会重算。
3. `server.py` 先等完成事件 0.75 秒，再可能等 0.2 秒；候选更新没有唤醒该完成事件。原始 HTTP 首候选观测集中在 0.95–1.00 秒，不能把它全部归因于原生候选算法耗时。

同时，原生只在预算层边界读取新 incumbent、决定证明 worker 数。若候选 worker 很快结束，而当前层很长，预留的一个 worker 要到下一层才会投入证明。

### 2.4 基线与报告口径需要固定

本地留存 EXE 的 SHA-256 为 `261d0afff67d1641d985d2587843c11c7130ca2edf9d4623eb69b5d6d04422fb`，与上一轮验收一致。其 build-info 中 12 个 C++ 文件的字节哈希与当前源码不同，后续 v1.6.1 有格式修复，v1.6.2 又修正 CI 构建。它可以作为历史强版基线，不能被标成当前源码刚刚重编译的结果。

此外，旧报告正文中的 Phase-1 SHA-256 被截短，正确完整值以 Q2 manifest 为准；旧报告仍保留当时本地包版本和“未远程发布”的叙述。下一轮应保留历史报告，并在新报告明确历史构建、当前源码构建和最终构建，避免混用。

## 3. 实施工作包

### N0：冻结当前强版、难例分层与热点测量

**文件：** `tests/benchmark_native.py`、`tests/benchmark_end_to_end.py`、汇总脚本；新增当前轮 manifest、难例选择文件与 profile 记录。

- [ ] 将历史强 EXE/build-info/manifest 保存为 S1-historical；从当前源码另构建隔离的 S1-source，不覆盖冻结基线，不修改已有 PDB。
- [ ] 首先在小集合确认两者行为一致并核对哈希；若有实质性能/语义差异，先解释，不把不同来源的结果拼成单一基线。
- [ ] 诊断子集固定为 `legal-20271000,01,03,05,06,07,09,13,18,26,28,31`：覆盖稳定超时、临界完成、偶数层和奇数层；正式验收仍使用全部公开 48 状态。
- [ ] 先固定完整排除 18/19 的预算对照，再为 20/21 层选可完整排除的状态；给超时数据打 censor 标记。找到解的最终层会提前停止，不能用其生成数波动判断等价变更改变了完整搜索树。
- [ ] 采样测 `canonical_index`、PDB 内存读取、逐轴转换、Corner、Tail 和分配调用占比；正式计时关闭重型 profiling。优先使用本机可用 CPU 采样工具，缺少硬件计数器时用采样计时与调用统计，不能直接宣布带宽是瓶颈。
- [ ] 增加逐轴 strong 查询/拒绝数、查询顺序、dual/BPMX 拒绝、方向采样成本、候选更新时间与 worker 归还时间。线程本地累计，避免每节点全局原子操作。
- [ ] 冻结一个新增的 32 个合法随机状态保留集，与现有验收和 PGO 种子去重。可固定种子 `2026092900..2026092931`；调参期间不根据该集合的表现选择策略。未证明深度保留未知。
- [ ] HTTP 基准记录“原生找到候选”“Python 接收”“HTTP 发出”“客户端收到”四个时间；profile 参数必须实际影响资产路由，不能只作为结果断言。原脚本 `--profile` 只检查实际返回配置，需完善其选择行为。

**验收：** 固定输入、可追踪 EXE/源码/资产、完整排除层和不同时间口径都有证据。不能把 12 个 oracle12 的亚毫秒解混入困难样本平均值，以掩盖超时。

### N1：将强表投影改为无分配的精确映射

**文件：** `native/include/strong_coords.hpp`、`native/src/strong_coords.cpp`、相关原生测试和微基准。

- [ ] 将上述 `L XOR K` 分解正式实现；保留慢参考函数供测试和初始化使用。热路径不再调用 `cube_from_sorted_slice`、`unrank_permutation`、通用 `CubieCube` 共轭。
- [ ] 先复用现有 64 KiB `phase1.flip_conjugates`，增加约 371 KiB 的全对称偏移表；若搜索只使用返回代表元的一个对称，再为每个 sorted 坐标预存 `symmetry、flip_offset、class_base`。
- [ ] `canonical_index` 变为少量查表、XOR、乘加。使用 uint64 计算组合索引和偏移，保持现有 3,529,433,088 项的编号逐项语义一致。
- [ ] 证明 `eo` 的 12 位变换对 11 个独立坐标位是仿射映射，遗漏的最后一位由偶校验线性恢复；验证所有 sorted/symmetry 的零/基向量和完整合法 cubie 随机对照。微基准通过不替代该证明。
- [ ] 用单线程固定次序、候选关闭、完整排除预算验证新旧查询值、生成数与剪枝数完全一致；再用 4 线程比较 wall 与吞吐，避免提前找到解造成访问数差异。
- [ ] 检查分配统计，搜索期间该坐标路径应为零堆分配；保留 byte 资产格式和原查询顺序，以便单独归因收益。

**验收：** 逻辑等价与完整层节点数一致，真实搜索有独立结果。无需重新生成大表；这是移除高频冗余计算，不是用近似 heuristic 替代准确距离。

### N2：加强 QTM 下界，压缩 20/21 步搜索树

**文件：** `native/src/solver.cpp` 的 `evaluate/expand/depth_first_search`，`solver.hpp`、`cube.cpp` 的紧凑逆状态辅助函数与测试。

**N2a，必须实现的三轴加强：**

- [ ] 在完整 QTM Phase-1 和强联合表上分别收集三个原始距离。三轴均为相同正数 `n` 时尝试使用 `n+1`；三轴全零必须仍为零，不能把复原态估成 1。
- [ ] 证明当前三个抽象的性质：从复原态做任一单位 quarter-turn，至少一个轴的抽象目标不变。把任意成本 L 的逆解展开成 L 个 quarter-turn，首步之后剩 L−1 步，因此至少一个轴下界 ≤L−1；若三个下界都为 n>0，则 L≥n+1。
- [ ] 必须对当前 sorted-slice 目标和对称约定检查该性质，并将证明写入代码注释和报告；不能只复制 HTM 的开关。若实际投影不满足前提，保留原 max 并报告反例，改用可证明的组合。
- [ ] 与已有根 QTM parity 合并，继续保留 18 种加权动作和标准同面合并规则；不要再把已经实现的奇偶跳层统计成新优化。
- [ ] 给两类相等加强独立计数和开关，浅层 oracle 全量验证、抽象距离证书与中深度交叉验证均通过后启用。

**N2b，必须完成的选择性 dual 下界试验：**

- [ ] 利用 `d(s)=d(s.inverse())`，令新下界为正态与逆态合法下界的最大值。优先复用同一强表；不相加，也不把逆态解直接按原方向执行。
- [ ] 先制作慢参考，再实现紧凑 inverse 坐标提取，按条件惰性计算。比较仅根/任务边界、低 slack 节点、全部存活节点三种频率；不能恢复为每候选无条件堆分配/完整状态构造。
- [ ] 如果维护 inverse 增量状态，注意 `(s·m)^−1=m^−1·s^−1` 是左乘，不能把右乘转移表直接用于 inverse 更新。先证明并逐步对照，或从紧凑状态直接提取逆态坐标。
- [ ] 加入 weighted pathmax/BPMX 原型：`h_child=max(h_child,h_parent-cost)`、`h_parent=max(h_parent,h_child-cost)`；QTM 半转 cost=2。dual 下界可能不一致，不能把“可采纳”误当“一致”。
- [ ] 父节点因合法传播下界超过剩余预算时才剪去其他子树；禁止用未证明的双向搜索相遇规则截断。TT 仍比较完整键和 last-face 上下文，只缓存已排除事实。
- [ ] 记录额外查询成本、拒绝数、完整预算候选数和 wall。默认启用只接受整体耗时改善的策略；无收益的 dual/BPMX 也要提交实测结论。

**验收：** N2a 和 N2b 分别消融，证明下界始终合法。以减少困难完整层候选数为目标，而不是仅让 heuristic 的平均值变大。

### N3：修复并重做有预算的方向选择

**文件：** `native/src/solver.cpp` 的根初始化、方向探测和迭代控制；`solver.hpp`、CLI、进度与基准脚本。

- [ ] 方向选择不再要求已有 incumbent。对 s 和 s.inverse() 计算已有下界，使用较强根下界作为合法的全局下界；方向本身通过预先冻结的策略选择。
- [ ] 取消固定“深度 16”条件，探测预算对齐实际 QTM parity，并支持用户较小 max_cost。更新候选不能导致方向功能永远未启用。
- [ ] 在有歧义的状态用等节点预算探测两个方向。初始上限可设每方向 50,000 generated、累计 ≤100 ms、且 ≤剩余总时间 1%；到任一上限即停止。数值作为调参起点而非已证明最优值。
- [ ] 比较探测期间拒绝率、相同预算工作量及下界分布，不把“节点/秒更高”直接理解为“需要搜索的总树更小”。采样成本必须计入请求 wall/deadline。
- [ ] 对样本太小或结果接近的情况使用稳定回退策略。早期预算已完整排除的证书可复用；未完成采样只用于排序/选方向，不推进 `completed_depth`。
- [ ] 根状态转换后重建一致的搜索坐标；返回公式逆转并执行验证。不要在同一未完成子树中任意切换正逆方向。
- [ ] 在全无候选的随机集合、奇偶预算、超时、取消、动态上界、正逆对照中验证；报告实际选择逆向的次数与成本。

**验收：** 原先 96 次随机运行全部未启用方向选择的限制被消除；收益来自相同 4 线程和相同条件的完整数据，不能只展示个别逆向更快的状态。

### N4：4-bit 精确强表与查询流水线

**文件：** `native/include/strong_pdb.hpp`、`native/src/strong_pdb.cpp`、`solver.cpp`、资产构建/验证/打包脚本、manifest。

- [ ] 从已完整验证的 byte 强表转换为独立新格式，两个精确距离打包为一个 byte。当前直方图最大值 14，0–14 可准确表示；完整表的 15 保留为非法/未覆盖标记，不得静默解释成有效距离。
- [ ] 转换时逐项比较解码值与源表，保留源 hash、目标 hash、坐标版本、metric、完整标记及直方图；这是无损格式转换，不必重新遍历 35 亿项抽象图建表。
- [ ] 旧 byte 读取器继续支持既有资产及部分表。首版 nibble 格式只接收完整且最大值 ≤14 的表；其他表保留原格式，防止截断或 unknown 语义混淆。
- [ ] `distance` 使用 `packed[index>>1]` 加移位与掩码；结果必须与 byte 版逐项一致。比较随机查询、实际 DFS、启动校验与峰值内存，不能以文件减半直接宣称搜索翻倍。
- [ ] 为 strong 查询提供 prepare-index 与 load-distance 两步接口，便于比较逐节点立即查询、同一父节点少量兄弟批量准备，以及选择性软件预取。批量方案最多保留固定容量候选，不改变完备性。
- [ ] 查询顺序至少比较：现有 Phase-1→Corner→Strong；单轴 Phase-1/Strong 交错；完整 Strong 支配对应 Phase-1 后省略重复查询。支配成立也不意味着省略便宜预筛一定更快，需用逐阶段总成本决定。
- [ ] 尽量逐轴更新 sorted 坐标，通过前轴后再更新后轴；当前代码进入 strong 段会先更新三个轴，适合单独测量惰性更新收益。早退后未初始化的字段不可被接受节点使用。
- [ ] 每项改动单独开关。byte/nibble、查询顺序和预取分别比较，不把节点变化与内存布局变化混为一种收益。

**验收：** 精确值一致、主体存储减半、实际资产可部署。默认流水线满足困难完整层总耗时改进；没有收益的预取/批量策略可关闭，但压缩资产和正确读取器必须交付。

### N5：缩短初始化与首次候选交付

**文件：** `strong_pdb.cpp`、`pdb.cpp`、`tail.cpp`、`native/src/main.cpp`、`cube_app/native.py`、`server.py`、`tests/benchmark_end_to_end.py`。

- [ ] 拆分初始化计时：坐标/对称辅助表、Corner/Phase-1、Strong、Tail、校验、候选 Phase-2 小表。当前 strong loader 顺序扫描全表并计算 checksum/max/unknown，不可把 5 秒全部称为磁盘读取。
- [ ] 为新资产格式提供可并行核验的分块 checksum/哈希及元数据完整性校验。全部必需块核验通过后才能用于严格剪枝；不能直接关闭校验，也不能仅凭 mtime/size 复用可信标记。
- [ ] 测试分块预读与并行校验的最佳线程数，并给物理内存预取设上限。Windows `PrefetchVirtualMemory` 只作为 I/O 提示，调用成功不代表数据已校验或全部驻留。
- [ ] 在服务启动时尽早准备候选所需的小资产；允许在强表/Tail 完整校验前，用已校验的基础表提供候选和较弱的严格搜索。未加载大表不能阻塞所有合法候选路径。
- [ ] 采用不可变、带版本的资产快照。活动搜索升级资产时，在预算层边界切换；若为避免长层等待需要提前升级，应取消该未完成层，从根用新坐标重启，不提升其完成深度。
- [ ] 缓存证明绑定正确的规则与坐标语义；切换更强合法下界不撤销已经完成的排除事实，但不得复用旧资产中的未初始化坐标或未完成前沿。
- [ ] 对候选更新增加独立通知事件或条件变量；HTTP 等待“候选可用或任务结束”，而不是只能等 `_done`。候选出现后立即响应或被轮询读到，解除 0.75+0.2 秒固定等待造成的延迟。
- [ ] 分别记录原生首次找到、服务收到、客户端看到的时间；候选已找到但尚未发送与候选尚未算出要区别统计。前端的旧请求隔离、模式切换和取消行为保持正确。
- [ ] 新进程分别测无预热首次请求、热文件缓存重启、已就绪服务请求；不能把后台预热时间从“首次使用”指标中抹掉。

**验收：** 3 秒短请求在初始化阶段仍能按统一 deadline 返回候选或明确超时；候选交付 p95 与完整强资产 ready 分开测量。损坏、缺失、只读和 Unicode 路径测试通过。

### N6：新候选与线程资源及时进入当前证明

**文件：** `native/src/solver.cpp` 的 `SearchControl`、worker pool、incumbent 控制；`fast.cpp`、`main.cpp`、`cube_app/native.py` 和生命周期测试。

- [ ] 在现有低频检查点读取经过验证的新上界和 generation，减少候选到达后等整层完成的延迟。候选更新保持不可变快照或锁保护，不在每节点复制公式。
- [ ] 如果新候选成本 U 已由 `proven_through ≥ U−1` 或合法下界证明，立即终止无必要的当前层并返回已证明结果。不能仅因为“找到更短候选”就把未完成层判为失败。
- [ ] 若当前预算高于还需排除的最大成本，可在安全屏障处取消并重排搜索；取消原因与用户取消/超时分开记录，任何未完成层都不能进证明缓存。
- [ ] 候选 worker 结束时，在当前预算层内将空闲名额交还证明池。用线程总配额和任务领取屏障实现，不必先重写成工作窃取；避免证明和候选各自使用全部核数。
- [ ] 补齐 `threads=1` 和无限时请求的候选策略。当前代码在这两种条件下不启动原生候选；单线程用有界时间片交替，无限时仍给候选器有限初始化/改进预算，不允许第二个失控搜索。
- [ ] 候选六方向调度基于首解时间和改进收益重新比较，不固定让第一个方向消耗 40% 的全部预算。首次解与后续质量优化设置独立时间份额，并尊重同一请求 deadline。
- [ ] 保留 0.5/1/3 秒的候选成本曲线，并记录实际证明 CPU 时间。仅用更多候选 CPU 换取更短公式而拖慢证明，不算整体收益。
- [ ] 测试候选恰在层结束、取消、超时、资产升级时到达，保证只有一次有效终态，无悬挂 worker、无跨请求结果和错误最短标记。

**验收：** 候选到达和线程归还不再被长预算层阻塞；纯证明基准继续关闭候选，端到端另以相同总线程数验证用户可见收益。

### N7：统一验收与交付

- [ ] N1 坐标零/基向量与完整 cubie 对照；N4 全项无损转换；N2 独立 QTM 半径 5 的 105,046 状态 oracle 和中深度双向对照全部通过。
- [ ] 组合开关覆盖 HTM/QTM、byte/nibble、无/部分/完整表、1/4/8/16 线程、正/逆方向、候选开关、TT 关闭/开启、取消和重复请求。不以生产搜索自身答案作为唯一 oracle。
- [ ] 完整公开 48 集维持 4 线程、60 秒、3 次重复，继续含所有超时与公开极端状态。历史强版与新强版用同样候选和缓存策略，不合并动态候选结果充当核心成绩。
- [ ] 新增 32 个未见合法随机状态至少三次重复，报告同条件成功率与 PAR-2。公开集用于诊断和调参，不能在新报告中把它称为未见集。
- [ ] 同样的诊断集按 1/4/8/16 线程测扩展性；可以建议生产配置，但主验收仍保持 4 线程。
- [ ] HTM、二阶、API/UI、取消、缺资产回退、格式、发布预检全部通过。生成并实际启动本地 Windows 包，验证新格式自动选择、旧格式兼容与强表损坏降级。
- [ ] 保留所有失败策略的样本级结果；给配对统计附样本数和离散程度，重复三次不代表精确 p95。正式性能运行与编译、建表、profile 分开进行。
- [ ] 发布 `qtm-next-optimization-report.md`、全部原始/摘要 JSON、源码和资产 hash、默认策略与未达目标。远程发布按届时用户授权执行。

**验收：** 新方案确实解决当前强版的困难状态和延迟，不只继续放大与旧弱版的对比倍数。未达到的目标继续明确保留。

## 4. 暂不作为本轮主线的方向

| 方向 | 当前判断 | 重新提升优先级的条件 |
| --- | --- | --- |
| 继续增大 Tail 到 9/10 | 现有大多数失败分支到不了 Tail；Tail-8 深查询次数极少 | N1/N2 后实测表明较大反向球能显著减少完整层，且资源预算允许 |
| 默认开启更多六棱块 PDB 或全层 TT | 上轮没有稳定 wall 收益，TT 单状态还没有命中 | 先用新的困难分层样本证明额外拒绝足以抵消计算/内存访问 |
| 重写 work stealing | 当前负载基本均衡；N6 只是归还预留名额 | 新查询策略后出现持续 idle、长尾或锁等待热点 |
| GPU、分布式、大型全状态双向搜索 | 对当前明确的坐标构造开销不是直接解法 | CPU 热路径与剪枝完善后，完整难例仍达不到目标，且另有可执行资源预算 |
| 模 3 压缩 | 本轮最大值 14 可用简单精确 4-bit；加权半转不能直接沿用 ±1 跟踪 | 有完整的 QTM 加权恢复证明和优于 nibble 的实测结果 |
| PGO 当主要交付 | 上轮增加吞吐但未提高完成层，不能代替算法改进 | 核心结构稳定后，用独立训练/验收集单独测试 |

这些方向可以保留研究记录，但不得抢占 N1–N6 的主要执行时间。若所有必做步骤后仍未达目标，再立项更大抽象表或外部硬件路线，并提供真实成本估计。

## 5. 对照矩阵与执行顺序

实施顺序为 `N0 → N1 → N2a → N3 → N4 → N2b → N5 → N6 → N7`。N2b 放在热路径和压缩后评估，避免用昂贵原投影误判 dual 查询没有价值。各阶段独立提交，最终再测组合。

| 对照 | 相对上一列的唯一主要变化 | 判据 |
| --- | --- | --- |
| S1-source | 当前源码重建、冻结 | 与历史强版差异可解释 |
| S2 | 无分配仿射坐标映射 | 同树、更低 wall |
| S3 | QTM 三轴加强 | 下界合法、完整层更少生成数 |
| S4 | 有预算方向选择 | 计入采样后仍改善难例时间 |
| S5a/S5b | byte/nibble；随后调整查询顺序 | 精确值一致、内存及时间各自报告 |
| S6 | 选择性 dual；再分别开 BPMX | 额外查询后仍有整体收益 |
| S7 | 初始化/候选通知/实时协作 | 端到端等待与质量改善，独立证明不退化 |

性能采用两条主线：纯证明关闭原生候选，固定相同已给候选或全部不提供候选；端到端启动候选器，固定总线程数和统一 deadline。cold/warm、候选完成/证明完成都单独计时。

正式 48×3×60 秒每配置最坏约 2.4 小时。开发期间先跑固定诊断集和完整浅预算，排除明确退化的实现；最终对冻结基线和最终候选运行完整集，不对每个微调重复整套长基准。

## 6. 现有可运行命令与待新增能力

当前即可复现坐标验证，不修改生产 EXE：

```powershell
New-Item -ItemType Directory -Force .cache/qtm-round2-analysis | Out-Null
& 'C:/msys64/ucrt64/bin/g++.exe' -std=c++20 -O3 -march=x86-64 -mtune=generic -flto -DNDEBUG -I native/include docs/benchmarks/qtm-round2-coordinate-probe.cpp native/src/cube.cpp native/src/symmetry.cpp native/src/strong_coords.cpp -pthread -static -o .cache/qtm-round2-analysis/coordinate_probe.exe
& ./.cache/qtm-round2-analysis/coordinate_probe.exe
```

当前保留 EXE 的强配置对照命令。它是历史强版，N0 完成后用 `--binary` 指定冻结的新源码构建；新输出不覆盖已有报告：

```powershell
& ./.venv/Scripts/python.exe tests/benchmark_native.py --metric QTM --cases-file tests/qtm_acceptance_public_cases.json --cases legal-20271000,legal-20271005,legal-20271013,legal-20271028 --threads 4 --timeout 5 --repeats 3 --variants staged --profile q4-strong --pdb-manifest docs/benchmarks/qtm-q4-profile-manifest-2026-09-28.json --incumbent-mode none --native-flag=--no-native-candidate --max-cost 18 --output .cache/qtm-round2-s1-cost18.json
& ./.venv/Scripts/python.exe tests/benchmark_native.py --metric QTM --cases-file tests/qtm_acceptance_public_cases.json --cases all --threads 4 --timeout 60 --repeats 3 --variants staged --profile q4-strong --pdb-manifest docs/benchmarks/qtm-q4-profile-manifest-2026-09-28.json --native-flag=--no-native-candidate --output .cache/qtm-round2-s1-public48.json
& ./.venv/Scripts/python.exe -m pytest tests/test_native_solver.py tests/test_metric_search.py tests/test_metric_api.py tests/test_search_lifecycle.py -o cache_dir=.cache/pytest-cache
```

方向对照可在相同命令添加已有 `--native-flag=--inverse-direction`，显式关闭探测可用 `--native-flag=--no-direction-probe`。比较完整层时应根据根 parity 选择 18/19/20/21；超时不能计成已完整排除。

实施 AI 需增加并文档化以下能力；这些不是当前已存在的 CLI 参数：

```text
--coordinate-kernel=reference|affine
--qtm-axis-rule=off|phase1|strong|both
--direction-policy=off|legacy|bounded
--dual-policy=off|root|selective|all
--bpmx=off|on
--pdb-query-order=legacy|interleaved|strong-first
convert-strong-pdb SOURCE TARGET --encoding=nibble --verify-all
--asset-loading=eager|staged
```

隔离编译输出与 build-info 也要加入构建脚本。当前 `native/build.ps1` 固定输出到生产 build 目录，N0 冻结前不要用它覆盖唯一历史 EXE。修改后必须重新编译再测试，昂贵检查按阶段执行。

## 7. 给实施 AI 的可复制指令

```text
执行 docs/ai-qtm-next-optimization-plan.md 的 N0–N7，完成第二轮 QTM 强优化。
上一轮完整基础 PDB、强联合表、Tail-7/8 和原生候选器已经交付；复用这些资产，
不要重做旧方案，也不要只与旧 HTM 下界版对比。

先冻结当前历史强 EXE，再从当前源码隔离构建新基线。优先正式实现已经通过
独立原型验证的 strong 坐标仿射查表，消除每次查询的完整状态构造与堆分配。
随后实现有证明的 QTM 三轴加强、不依赖初始候选的有界方向选择、4-bit 精确
强表，并完成选择性逆状态下界和加权 BPMX 的正确原型与消融。

继续处理经过校验的分阶段加载、候选事件立即交付、新 incumbent 和候选线程
资源及时进入当前证明。单线程、无限时、取消、缺表和格式兼容均需覆盖。

完整 48 状态的验收仍用 4 线程、60 秒、3 次，保留全部超时；新增未见随机集
单独验收。目标是当前强版 PAR-2 从 62.827 秒降到不超过 45 秒，证明完成数
从 80/144 提高到至少 108/144，并改善冷启动、内存和首候选等待。

坐标微基准约 121 倍仅证明该局部替代值得实现，不能声称整体同倍加速。
每一阶段报告完整搜索树/耗时/内存变化，未完成层不得变成证明，缓存重试、
多加线程、动态候选和未见集调参不得混入独立证明对照。

最终交付代码、准确资产及清单、可复现原始与汇总数据、本地可运行包和
docs/qtm-next-optimization-report.md。任何目标未达到都明确保留，依据证据
继续优化。不能只交付 N1 微基准或几个简单样本。远程发布不包含在本指令内。
```

## 8. 依据与本轮交付

项目依据：[上一轮报告](qtm-strong-optimization-report.md)、[公开验收](benchmarks/qtm-strong-acceptance-public-2026-09-29.json)、[Q6 消融](benchmarks/qtm-q6-ablations-2026-09-29.json)、[深层 Edge 筛查](benchmarks/qtm-q8-edge-deep-2026-09-29.json)、[候选结果](benchmarks/qtm-strong-candidates-2026-09-29.json)。本轮再分析和微基准完整数据见 [qtm-next-optimization-analysis-2026-09-29.json](benchmarks/qtm-next-optimization-analysis-2026-09-29.json)。

三轴相等加强的原始思路来自作者的 [The Optimal Solvers](https://www.kociemba.org/math/optimal.htm)，本方案要求针对当前 QTM 和 sorted-slice 投影补全证明。dual 下界及其不一致性、BPMX 的理论背景来自原论文 [Dual Lookups in Pattern Databases](https://tzin.bgu.ac.il/~felner/2005/dualpdb.pdf)；不套用论文中的性能倍数。Windows 预读行为以 [PrefetchVirtualMemory 文档](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-prefetchvirtualmemory)为准，不将其视为校验或驻留保证。

方案阶段的初始交付只包含本方案、分析 JSON 和坐标微基准源码；当时未修改或部署生产求解器，也未重新运行上一轮多小时的完整验收。后续实施与正式验收见[QTM 第二轮报告](qtm-next-optimization-report.md)。
