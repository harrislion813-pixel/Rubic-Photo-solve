# QTM 第二轮强优化实施报告

日期：2026-09-29。对应 [行动方案](ai-qtm-next-optimization-plan.md) 的 N0–N7。本报告的正式纯证明对照固定为 QTM、4 线程、60 秒、每状态 3 次，关闭原生候选和证明缓存。候选与 HTTP 结果另行统计。

## 构建与样本

历史强版 EXE 已原样冻结在 `.cache/qtm-round2/s1-historical`，SHA-256 为 `261d0afff67d1641d985d2587843c11c7130ca2edf9d4623eb69b5d6d04422fb`。它与上一轮公开验收的二进制相同，不能称作当前源码重编译版。从提交 `660988c25ef35244c5a002f16b03236aa4df2342` 的独立 worktree 构建了 S1-source，SHA-256 为 `7f75b9341fb8f0dea2a65054465abecb788da0f617e685856c37d9f8e7491df6`。两者在两个固定 18 成本完整排除状态的生成数完全相同（19,879,431 和 23,722,716），计时分别为历史版 1.706/1.997 秒、源码版 1.690/2.001 秒。正式历史基线沿用已校验哈希的上一轮 [48 状态汇总](benchmarks/qtm-strong-acceptance-public-2026-09-29.json)：80/144 次证明，PAR-2 62.827 秒。

新增的 [32 个未见合法状态](../tests/qtm_round2_unseen_cases.json)在调参前冻结，种子为 `2026092900..2026092931`，与公开验收、原验收和 PGO 文件逐个排重。[12 状态诊断集](../tests/qtm_round2_diagnostic_cases.json)覆盖此前稳定超时、临界完成及两种 QTM 奇偶层。未证明状态的最短深度仍标为未知。

公开运行的 PDB 清单 SHA-256 为 `c7e61e8395e7cb63746208963f1a725a0891add78a068b1bb708d71d0826c287`；未见运行开始时清单有两处换行格式变化，SHA-256 为 `5d2e01bc3b9c6999ecbaa4d2fc182a6a02db8de40f77908c7987f686804a97d4`。[未见清单字节快照](benchmarks/qtm-round2-unseen-manifest-snapshot-2026-09-29.json)与公开清单解析后的 JSON 完全相同；正式汇总已再次确认两轮运行的二进制与各资产字节哈希逐项一致。

## 核心实现与正确性

**N1 坐标。** 强联合表的索引改成代表元类基址、Phase-1 翻转共轭与按 sorted-slice 预存的 XOR 偏移。慢参考路径仍可用 `--coordinate-kernel=reference` 选择。对每个 sorted-slice/对称的零向量和 11 个独立翻转基向量、1,048,576 个坐标样本，以及 100,000 个合法 cubie 随机游走状态，共 3,429,536 次新旧索引对照一致。翻转的第 12 位由偶校验确定；对固定 sorted-slice 和对称变换，剩余 11 位是仿射函数，故零向量与基向量检查覆盖所有合法翻转。同样的 4,194,304 次索引微基准中，参考路径每轮出现 12,582,912 次堆分配，仿射路径为零；三轮中位计时分别为 0.5661 秒和 0.00593 秒。此处不含 PDB 随机读取、DFS 或多线程，局部速度不能外推为整个求解器速度。

隔离单线程、byte strong、原查询顺序、关闭三轴规则/方向/候选，对 `legal-20271000` 和 `legal-20271005` 完整排除成本 18：参考/仿射路径生成数、节点数、各 PDB 查询及拒绝数逐项相同；墙钟分别为 6.003→3.178 秒和 6.987→3.721 秒。这是同树的真实搜索收益，约 1.89 和 1.88 倍。

**N2a 三轴下界。** QTM Phase-1 与完整 strong 表分别在三个距离都等于正整数 `n` 时使用 `n+1`，零距离仍为零，并各有开关与拒绝计数。行动方案中“任意状态做首步后至少一个轴在目标”的说法对任意状态不成立；实际有效的证明取**最后一步**：把任意复原公式展开成单位 quarter-turn，在最后一步之前的状态是复原态的一个 quarter-turn 前驱，因此至少一个轴投影已经在目标。其距离至多为总成本减一；三个距离若都为 `n>0`，总成本至少 `n+1`。已对当前 Phase-1 与 sorted-slice 的 12 个单位转动逐一核验目标投影。最终 EXE 带完整 nibble strong 表再次运行独立 QTM 半径 5 BFS oracle，通过全部 105,046 状态，没有启用小表作为掩护。

**N2b dual/BPMX。** dual 下界取原态与逆态合法下界的最大值；逆态从栈上重建的紧凑坐标提取，未错误地把右乘转移套到逆态。实现 root、低 slack、全部节点三个频率。加权 pathmax/BPMX 按 QTM 单转成本 1、半转成本 2 传播，只有传播后的父下界超出预算才剪枝，TT 仅记录已完整排除的节点。原型已做消融；默认策略依据墙钟结果选择。

**N3 方向。** QTM 根下界同时查询正态与逆态，较强者可作为全局合法下界。根逆态下界更强时选逆向；相等时双向各最多采样 50,000 generated，总计不超过 100 毫秒且不超过请求时限 1%，实际探测层与 QTM 奇偶及最大预算对齐。探测未完成的层只用于选择方向，不进入完成深度。逆向所得公式先还原并做整魔方验证。

**N4 强表。** 原 3,529,433,088 字节距离主体无损压为 1,764,716,544 字节。v4 nibble 只接受已完整、最大距离至多 14 的 QTM strong 表；值 15 保留为非法标记。转换逐项解码对照源 byte 表，得到相同直方图与最大值 14。每个 64 MiB 块有独立校验和，加载时并行核验所有块与距离范围。旧 byte 和部分表读取路径仍保留。新资产的 [清单](benchmarks/qtm-round2-nibble-manifest-2026-09-29.json)记录源、目标 SHA-256。查询实现提供 prepare-index/load-distance 与可选预取，并比较旧查询顺序、Phase-1/strong 逐轴交错、完整 strong 优先；完整 strong 支配同轴 Phase-1 后可省去其重复读取。后轴坐标按需更新。

**N5/N6 服务和候选。** 原生服务可选 eager/staged 资产加载，staged 在基础表和候选小表完成后立即 ready，强表和 Tail 完整核验后发布不可变资产快照；活动证明只在预算层边界升级并从根重建坐标。HTTP 现在等候候选或终态通知，候选出现即唤醒，分别记录原生找到、Python 接收、HTTP 发出和客户端收到时间。证明按低频检查点读取已验证新上界，只有完成深度足够时才宣布最短；新候选缩短未完成层时独立标记并禁止把该层写入证明缓存。候选 worker 结束后，预留证明 worker 可在当前层加入任务队列。单线程采用限时前置候选时间片，无限请求仍给候选有限预算；六方向候选器采用均分的首解和改进时间份额。

## 固定预算消融

固定 12 状态、4 线程、完整排除 18 成本、关闭候选和方向，以 nibble strong、strong 优先查询对照三轴开关：三轴均关闭时生成数几何平均为启用后的 **1.492 倍**。strong 相等拒绝每状态约 5 万至 69 万次；strong 优先的完整表已跳过被支配的 Phase-1 查询。选择性 dual 进一步减少约四分之一生成数，但这批状态墙钟几何平均变慢约 6%；BPMX 单独未给出稳定收益，两者默认关闭。所有生成数仅比较完成的排除预算，不将找到解后的不完整最终层纳入等树结论。

补测 root/selective/all dual 和 all+BPMX：root 与关闭时同为 120,874,977 个生成候选；selective/all 均约 96,612,228 个，后者额外做了约一万次逆态查询而无额外拒绝。all+BPMX 有 767 次传播拒绝，生成候选降至 96,607,725，但 12 状态总墙钟为 4.738 秒，高于未开 dual 的 4.076 秒。该组补测使用最终 EXE，前述原始 axis/selective/BPMX 消融使用其前一隔离构建；两版的坐标与剪枝源码一致，最终构建另调整了候选时间片，纯证明一律关闭候选。

用最终 EXE 在同一固定排除层比较 byte/nibble：生成候选同为 120,874,977；12 状态总搜索墙钟分别 4.788/4.599 秒，逐状态 byte/nibble 耗时比几何平均 1.043，峰值工作集约 5.10/3.45 GiB。byte/nibble 的 eager 启动约 5.25/8.47 秒，说明 nibble 降低内存且搜索略快，但完整校验使启动变慢。nibble 上软件预取开关的生成数同为 120,874,977，总墙钟 4.599/4.596 秒，差异不足以支持默认预取，故保持关闭。

完整排除 18 成本的生成数改善尚未达到计划中的 2 倍目标。选定两个更深状态关闭候选、都运行至 `budget_exhausted` 且确认完成指定层：`legal-20271003` 的 20 成本上限，历史/最终生成数为 188,255,898/124,673,895，墙钟 17.401/4.767 秒；`legal-20271000` 的 21 成本上限，分别为 1,785,172,827/1,178,341,899，墙钟 165.212/45.258 秒。两者生成数比为 1.510/1.515，墙钟比约 3.65。20/21 层同样没有达到 2 倍生成数目标；这些是完整排除证书，未把超时或找到解后的未完成层计入。

同一 12 状态固定排除层的线程扩展性：1/4/8/16 线程生成候选都为 120,874,977，总搜索墙钟分别为 12.711/4.591/2.134/1.281 秒。4→16 线程约快 3.58 倍；正式公开与未见验收仍固定为 4 线程，不能将线程收益计入算法收益。

## 正式验收

公开 48 状态与冻结未见集的三轮正式运行均已完成。公开对照如下，超时按 120 秒计入 PAR-2，未计作成功证明：

| 指标 | 历史强版 | 本轮最终 EXE |
| --- | ---: | ---: |
| 完成证明 | 80/144 | 120/144 |
| 其中随机状态 | 44/96 | 84/96 |
| PAR-2 平均秒数 | 62.827 | 32.061 |
| 进程峰值工作集 | 5.09 GiB | 3.45 GiB |
| 新进程完整强配置初始化中位秒数 | 5.229 | 8.507 |

在两版各三次均完成、且历史版中位耗时至少 1 秒的 12 个状态上，逐状态中位耗时比的几何平均为 2.738 倍，范围为 0.429–3.896 倍。因此总体收益不是每个状态都提速；逐状态结果将保留在正式摘要中。公开证明成功数、随机成功数、PAR-2、困难状态配对加速、内存目标均达到方案目标，完整强表初始化未达到 2 秒目标。

最低比值来自 `legal-20271018`：历史版中位 2.832 秒，本版 6.595 秒。本版三次均选了逆向，生成数分别约 1.62 亿、1.95 亿、2.90 亿；历史版前两次正向仅约 0.365 亿，另一次约 2.50 亿。方向策略对该状态的选择不佳。正式结果仍冻结该策略，未用此个案或未见集临时改动二进制。

冻结未见集共 32 个合法随机状态、96 次运行，完成 72/96 次严格证明，PAR-2 为 45.036 秒。21 个状态三次均完成，6 个三次均超时，其余 5 个有部分完成。未见集没有用于调参；公开与未见原始文件的最终 EXE SHA-256 均为 `0dbbe2b62c5b38b0e685b4ae5a25608eca690fdff0dfe9f171d4fcb3ec866fd4`，四项 PDB 的字节大小与 SHA-256 逐项一致。逐状态三次结果见[正式摘要](benchmarks/qtm-round2-summary-2026-09-29.json)和[原始数据压缩包](benchmarks/qtm-round2-raw-2026-09-29.zip)，[索引](benchmarks/qtm-round2-raw-index-2026-09-29.json)记录包内 43 个 JSON 的字节数与 SHA-256。

## 启动、内存与候选

正式 eager nibble 服务的完整 strong 校验中位约 7 秒，热文件缓存条件下也未达到 2 秒目标；staged 的基础 ready 实测约 0.84 秒。前者是真正完整强资产可用于严格剪枝的时间，后者只是基础资产就绪，不混写。公开正式运行的 nibble 进程峰值工作集为 3.45 GiB，历史 byte 为 5.09 GiB。
本轮没有人为清空 Windows 文件缓存；上述启动数据是重复启动进程后的热文件缓存条件，真正冷文件缓存启动时间尚无可靠测量。

32 状态、每请求 3 秒的 staged HTTP 对照中，候选在所有 32 个请求中出现；首候选客户端接收时间的样本 p95 与候选时间份额如下：
HTTP 服务按本机 16 个逻辑处理器的默认设置给每个原生请求 15 个线程；三组消融采用相同设置，与上文固定 4 线程的纯证明验收分别统计。

| 候选时间份额 | 首候选 p95 秒 | 候选代价中位 | 3 秒内完成证明 |
| ---: | ---: | ---: | ---: |
| 15% | 0.047 | 25 | 9/32 |
| 35% | 0.062 | 24.5 | 10/32 |
| 60%（默认，首次） | 0.062 | 24 | 10/32 |
| 60%（默认，计时字段复测） | 0.062 | 24 | 8/32 |

默认策略达到首候选 0.5 秒和代价 24 的目标。首个新进程冷请求取得候选并完成简单证明耗时约 1.59 秒，使用基础资产；不能将其当作已完成 strong 校验后的响应时间。此处 p95 来自单轮 32 个样本，只可作样本分位数，不能称精确总体 p95。
这组 staged 请求中，前 3 个结束时仍使用基础资产，后 29 个使用 strong；仅取后 29 个的首候选样本 p95 为 0.047 秒。表中 0.062 秒是全部 32 个请求的混合口径。

同一默认 60% 候选时间份额下，另测 0.5/1/3 秒请求曲线：

| 请求期限 | 首候选样本 p95 秒 | 候选代价中位 | 完成证明 | 证明 worker 忙碌秒数中位 |
| ---: | ---: | ---: | ---: | ---: |
| 0.5 秒 | 0.047 | 25 | 2/32 | 5.086 |
| 1 秒 | 0.062 | 25 | 5/32 | 13.172 |
| 3 秒 | 0.062 | 24 | 8/32 | 22.123 |

worker 忙碌秒数为同一请求内各证明线程忙碌墙钟的总和，不是整个进程的 CPU 计数器时间。随着期限增长，staged 的 strong 资产完成加载，三组请求结束时使用 strong 的数量分别为 17、24、29；因此短预算间的证明完成数同时受期限与资产阶段影响，不能只归因于候选时间份额。

## HTM、API 与运行矩阵回归

完整 pytest 套件 154/154 通过。运行矩阵覆盖 byte/nibble 强表、损坏文件头及数据块降级到 byte、缺 strong 降级到 standard、Unicode 路径和同服务重复请求。8 个 HTM 代表状态、每个 3 次、2 秒限时的历史/最终对照，均完成 6/24 次严格证明，其余保持相同超时口径。`repo14` 低于 5 毫秒，不能可靠用少量单次测量判断 10% 回退。`pgo16` 固定同树 10,160,820 个生成候选，另做 10 次重复后历史/最终中位 0.1662/0.1936 秒，慢约 16.5%；**HTM 代表性耗时回退不超过 10% 的目标未达成**。QTM 优化没有改变这个 HTM 搜索树，但当前二进制在该短状态上的单位候选处理变慢，需后续专门优化。

## 复现与交付

生产默认使用仿射坐标、QTM 双三轴加强、完整 strong 优先查询、有界方向选择；dual/BPMX/预取默认关闭。桌面服务默认 staged 加载，可用 `CUBE_NATIVE_ASSET_LOADING=eager` 要求 ready 前完整强资产。源码和构建来源见[构建清单](benchmarks/qtm-round2-build-manifest-2026-09-29.json)，资产来源见[nibble 清单](benchmarks/qtm-round2-nibble-manifest-2026-09-29.json)。

最终 portable 原生 EXE 在 `.cache/qtm-round2/final/cube_solver.exe`，SHA-256 为 `0dbbe2b62c5b38b0e685b4ae5a25608eca690fdff0dfe9f171d4fcb3ec866fd4`；同一文件及 build-info 已复制到 `native/build`。本地 [Windows ZIP64 包](../.cache/qtm-round2/local-release/RubicPhotoSolve-1.6.2-windows-x64.zip) 为 2,142,344,901 字节，SHA-256 为 `c60f02131826ce97e360ded7be910d2f2cc8d80174c3ed962a25cff619fba37d`。包内 EXE 和 nibble 强表哈希分别与冻结最终 EXE 和资产清单一致。[包验收 JSON](../.cache/qtm-round2/release-verification.json)记录了资产、eager、staged、缺 strong 的四组实启动检查：HTM/QTM 精确深度、取消后恢复、staged 从 base 升到 strong，以及缺 strong 降到 standard 均通过。完整 pytest 为 154/154 通过；`git diff --check` 通过。

正式[原始数据压缩包](benchmarks/qtm-round2-raw-2026-09-29.zip)为 8,925,292 字节，SHA-256 为 `43a71722111fdbba348367b3c7bc4de409304d2936939b4ff26b0b132eeea885`。可复现命令见 `tests/benchmark_native.py`、`tests/benchmark_end_to_end.py`、`tests/summarize_qtm_round2.py`、`tests/verify_qtm_round2_runtime.py` 与 `tests/verify_frozen_windows.py` 的参数；原始 JSON 保存每个样本的参数、资产和二进制哈希。

正式公开运行的核心命令如下；未见运行仅把 `--cases-file` 改为 `tests/qtm_round2_unseen_cases.json`，`--output` 改为 `.cache/qtm-round2/final-unseen32x3x60.json`，其余参数相同。`staged` 在这里是搜索扩展变体名，服务资产加载保持 eager，原始 `ready.asset_loading` 可核验。

```powershell
./.venv/Scripts/python.exe tests/benchmark_native.py --binary .cache/qtm-round2/final/cube_solver.exe --metric QTM --cases-file tests/qtm_acceptance_public_cases.json --cases all --threads 4 --timeout 60 --repeats 3 --variants staged --profile q4-strong-nibble --pdb-manifest docs/benchmarks/qtm-round2-nibble-manifest-2026-09-29.json --incumbent-mode fixed --native-flag=--no-native-candidate --output .cache/qtm-round2/final-public48x3x60.json
./.venv/Scripts/python.exe tests/summarize_qtm_round2.py --historical .cache/qtm-acceptance-strong-public48x3x60.json --public .cache/qtm-round2/final-public48x3x60.json --unseen .cache/qtm-round2/final-unseen32x3x60.json --candidates .cache/qtm-round2/e2e-staged-32x3-final.json --output docs/benchmarks/qtm-round2-summary-2026-09-29.json
./release/build_windows.ps1 -QtmProfile Strong -SkipNativeBuild -SkipTableBuild -OutputDirectory .cache/qtm-round2/local-release
```

仍未达到的计划目标是完整强资产 eager 初始化不超过 2 秒、固定完整层生成数至少减少 2 倍、HTM 代表状态耗时回退不超过 10%。真正冷文件缓存启动尚未测量。远程发布不在本轮任务范围内，本地包未上传。
