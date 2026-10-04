已按照 [2026-10-05 HTM 评审](htm-speed-review-2026-10-05.md) 完成 P0–P2 的实现、独立消融、默认入口验收和原生重编译。六照片状态的新旧 36 次真实 HTTP 请求中，严格最短完成数由 **11/18 增至 15/18**，PAR-2 由 **32.233 秒降至 19.680 秒，改善 38.9%**；没有新增超时。P3 完成独立强表设计里程碑，尚未生成强表，不能把本轮成绩归因于它。

**当前交付。** 应用默认采用 HTM 原生六方向两阶段候选器；单个候选工作线程与证明共享原有 15 总额度，候选总预算仍为 1.5 秒。内部候选上界及时发送、验证、采用；页面提前显示候选的 H1 开关仍默认关闭。缺少原生程序时保留 Python 候选路径。HTM/QTM 的距离表、动作成本及资产独立，二阶和 QTM 的相关回归通过。

| 工作包 | 实际改变 | 验证及限制 |
| --- | --- | --- |
| P0 活动层上界 | 监督线程在搜索层内读取新候选；记录 received / validated / adopted；区分找到解、上下界相遇、取消和原期限到达 | 正逆方向 × 1/2/3/15 线程 × 4 种迟到及竞争情形共 32 个原生场景通过；中断层不签发完成证书 |
| P1 对称映射 | raw→class/sym 合并为一个 uint32，预存 class×2187；主体每项 5→4 字节 | 全部 1,013,760 个 raw 映射与独立编译的旧实现指纹一致；主体减少 1,013,760 字节 |
| P1 专用展开 | 每层选择完整 Phase-1 + Corner、无 edge PDB 的固定路径；拒绝节点不补齐后续坐标 | 通用路径保留；专用与通用展开核对全部所需字段和截止界，并通过独立 cubie 浅层 oracle |
| P1 启动缓存 | 独立版本化 HTM 对称映射缓存，核对 metric、维度、长度、校验及映射一致性 | 损坏、截断、Unicode 路径及确定性重建回归通过；离线准备和安装校验覆盖新增缓存 |
| P2 原生候选 | HTM 自己的 Phase-2 单位成本 BFS 表、单方向和三轴正逆六方向；常驻协议、原期限内启动/等待/取消 | Python 和 C++ 各自回放公式；54 次隔离候选试验，实际 HTTP 完整策略验收后启用六方向默认 |
| P2 有界方向选择 | 初始候选为空也能探测；先比较根下界，再用至多 100,000 节点/方向及共享 12 ms 样本选择；最多切换一次 | 采样不计入完整层证明，遵守原期限；没有单独测得此项的端到端加速比 |
| P3 强表 | 独立 sorted-slice HTM 投影、构建预算、断点、证书及轻量回退设计 | [设计文件](htm-strong-table-design-2026-10-05.md)；本轮没有强表构建器、生成资产或性能成绩 |

P0 只有在可靠的 `completed_depth ≥ U−1` 时才能凭长度 U 的已验证候选停止活动层并确认最短；仍需排除 U−1 层时继续证明。用户取消、deadline 和活动层中断不增加完成深度。候选同步由监督线程执行，DFS 节点不增加候选互斥锁。协议复现有意使用评审中的已知公式和既有 16 层证书，仅验证迟到上界处理；这些输入从未用于下面的从零 HTTP 验收。[P0 全部记录](benchmarks/htm-opt-2026-10-05/p0-incumbent.json.gz)

**相同搜索树的独立消融。** 15 证明线程、正向、固定排除至 16 步；禁候选、证明缓存及方向探测。每项采用 AB/BA/AB，各版本各三次。表中的秒数是完整排除时间，不是求出最短公式的完整请求时间。

| 比较 | initial-1：旧→新 / 秒 | 耗时下降 | initial-12：旧→新 / 秒 | 耗时下降 |
| --- | ---: | ---: | ---: | ---: |
| P0 版本→仅 packed 映射 | 1.026→1.005 | 2.1% | 1.284→1.204 | 6.2% |
| packed→再加专用展开 | 1.002→0.891 | 11.1% | 1.262→1.038 | 17.7% |
| 原始版本→最终组合搜索路径 | 1.028→0.892 | 13.2% | 1.281→1.043 | 18.6% |

三项比较的累计生成量都分别为 **142,333,407 / 188,783,217**，各轴拒绝、同值加强拒绝、Corner 拒绝和 edge 拒绝逐项相等；任务入口重复查询计数允许调度差异。packed 单项没有在两个状态都达到评审建议的 5% 门槛；保留依据是映射内存减少、没有观察到同树退化，以及专用展开与完整组合通过验收，不能称其单独已达到双状态 5%。各项百分比不能简单相加。[packed 原始记录](benchmarks/htm-opt-2026-10-05/p1-packed-pair.json.gz)、[专用展开记录](benchmarks/htm-opt-2026-10-05/p1-specialized-pair.json.gz)、[组合记录](benchmarks/htm-opt-2026-10-05/final-same-tree-pair.json.gz)、[新旧映射指纹](benchmarks/htm-opt-2026-10-05/p1-reference-equivalence.json)。

启动缓存另做 AB/BA/AB，新进程、完整资产、OS/磁盘缓存暖态：从专用展开版本到启用对称缓存，启动中位数 **0.685→0.187 秒，下降 72.7%**。这包含完整初始化过程；没有关闭 PDB 资产校验，也不声称差额全部来自对称构造。[启动记录](benchmarks/htm-opt-2026-10-05/p1-startup.json)

**候选质量单独比较。** 以下是无证明竞争、缓存暖态、每次至多 1.5 秒、每种策略每状态三次的预算内最佳 HTM 长度；三次长度均一致。六方向仍只有一个候选工作线程，沿各方向顺序分配和回收未用预算。半转计一步。

| 状态 | Python 单方向 | 原生单方向 | 原生六方向 |
| --- | ---: | ---: | ---: |
| initial-1 | 20 | 19 | 18 |
| initial-12 | 19 | 19 | 18 |
| initial-2 | 22 | 21 | 20 |
| initial-5 | 20 | 19 | 19 |
| initial-8 | 21 | 20 | 18 |
| initial-16 | 22 | 20 | 19 |

initial-1 的已知最优是 18，原生六方向三次均达到；initial-12 的已知最优是 17，三种候选策略都未达到。两种已知最优状态共六次试验中，六方向达到三次，另外两种策略为零。候选长度下降仍可能留下昂贵的找到最优解层，不能直接换算为证明速度。[54 次候选曲线及回放记录](benchmarks/htm-opt-2026-10-05/p2-candidates.json.gz)

**真实默认请求。** Ryzen 7 9700X，8 核/16 逻辑处理器；新旧应用源码各自配对应二进制。状态为冻结的 `initial-1/12/2/5/8/16`。每次启动新的应用、证明与候选进程，表和 OS 缓存暖态；每请求 30 秒原入口期限，15 总额度，候选占一份并在结束后归还。清除环境中的 `CUBE_` 实验设置，不传最优公式、证明证书或生成打乱公式，性能请求串行运行。

36 次矩阵验收时，新版用 `CUBE_HTM_NATIVE_CANDIDATE=six` 指定待采纳策略；通过后将同一策略写入 `server.FAST_SOLVER` 默认构造。最终不设置任何实验开关的独立 HTTP 请求也通过，initial-1 在 12.797 秒确认 18 步最短。下表采用请求开始至终态及工作线程退出的墙钟时间，包括进程启动和清理；HTTP 轮询约 0.1 秒，超时墙钟可能略大于 30 秒。

| 状态 | 原版三次 / 秒，T=超时 | 新版三次 / 秒，T=超时 | 原版→新版中位数 / 秒 | 原版→新版超时数 |
| --- | --- | --- | ---: | ---: |
| initial-1 | 30.015 T / 25.360 / 25.625 | 12.485 / 12.515 / 12.422 | 25.625→12.485 | 1→0 |
| initial-12 | 16.969 / 16.828 / 16.859 | 14.594 / 14.047 / 13.860 | 16.859→14.047 | 0→0 |
| initial-2 | 6.078 / 5.812 / 5.390 | 4.781 / 5.141 / 5.359 | 5.812→5.141 | 0→0 |
| initial-5 | 13.953 / 13.578 / 13.750 | 12.360 / 11.750 / 11.453 | 13.750→11.750 | 0→0 |
| initial-8 | 30.047 T / 30.109 T / 30.125 T | 14.391 / 14.531 / 14.547 | 30.109→14.531 | 3→0 |
| initial-16 | 30.062 T / 30.047 T / 30.094 T | 30.031 T / 30.125 T / 30.062 T | 30.062→30.062 | 3→3 |

PAR-2 使用完成请求实际秒数、30 秒未完成请求计 60 秒，再对每版 18 请求求均值。改善 38.9% 超过评审建议的 15%，既有状态没有增加超时。六照片组只支持此范围的结论，不能当作任意打乱的保证或总体 p95。所有慢记录和超时都保留，**initial-16 仍三次超时**。[36 次完整原始记录](benchmarks/htm-opt-2026-10-05/http-matrix-v2.json.gz)、[统计汇总](benchmarks/htm-opt-2026-10-05/http-summary.json)、[逐请求事件和资源精简记录](benchmarks/htm-opt-2026-10-05/acceptance-summary.json)、[最终无开关入口记录](benchmarks/htm-opt-2026-10-05/final-default.json.gz)。

内部首候选、原生实际采用和页面发布分别记录，以下为新版每状态三次中位数，均从请求创建计时。页面发布时间是服务产生可供页面读取结果的事件，实际浏览器渲染延迟未测；原版没有原生 adopted 事件，不能推断其收到即采用。

| 状态 | 原版首候选 / 秒 | 新版首候选及内部上界 / 秒 | 新版首次原生 adopted / 秒 | 原版→新版页面发布 / 秒 |
| --- | ---: | ---: | ---: | ---: |
| initial-1 | 0.953 | 0.828 | 0.891 | 2.281→2.000 |
| initial-12 | 0.860 | 0.875 | 0.937 | 2.281→2.204 |
| initial-2 | 1.015 | 0.828 | 0.859 | 2.281→2.203 |
| initial-5 | 0.829 | 0.860 | 0.953 | 2.282→2.265 |
| initial-8 | 1.047 | 0.828 | 0.875 | 2.266→2.172 |
| initial-16 | 1.093 | 0.844 | 0.922 | 2.281→1.953 |

这里没有把候选隔离试验的生成时间冒充页面时间，也没有宣称首候选在每个状态都更快。首次 adopted 的候选未必是预算内最好候选；精简记录保留每次后续改善的成本和时刻。

**资源与交付体积。** 矩阵中各进程 CPU 时间之和的中位数为 **280.508→176.977 CPU 秒**；这是 Windows 进程生命周期 CPU，包括 Python 导入和原生初始化，并非纯 DFS 时间。每请求各进程的生命周期峰值工作集相加，再取 18 请求中的最大值，为 **448,409,600→423,477,248 B（约 427.6→403.9 MiB）**。该值不是同时采样的进程树峰值，也不是 p95；原始数据分列 Python、证明及原生候选进程。

新增缓存为 `phase1_symmetry_htm_v1.bin` **4,464,200 B** 和 `phase2_htm_v1.bin` **2,742,056 B**，合计 **7,206,256 B，约 6.87 MiB**。本地 HTM exe 为 **3,835,111→3,955,091 B**，增量 119,980 B。这是文件大小而非压缩安装包增量；本轮未制作或发布新的安装包。离线缓存准备完成，当前本地 `QtmStrong` 清单及安装校验通过，共 21 项资产；强表的大资产没有加入默认包。

**正确性与最终构建。** 109 项 pytest 回归全部通过（35.82 秒），包括真实原生迟到候选、停止原因、损坏缓存、缺表/通用路径、取消/期限、候选进程复用、HTTP 1/2/3/15 总额度退出、任务所有权及释放、HTM/QTM 隔离、二阶和发布资产契约。矩阵中 439 条出现的公式声明由 Python cubie 独立回放并核对 HTM 长度；所有请求没有 fallback/candidate_error，清理后没有 HTM 额度持有者。[最终测试结果](benchmarks/htm-opt-2026-10-05/contracts-final.xml)

额外先用固定种子 `20261005` 冻结八个独立随机状态，再调用最终无开关 HTTP 默认入口；只发送状态，不发送生成动作或逆解。八个状态均确认最短，长度为 5/6/7/8/9/10/10/12，墙钟 0.203–0.281 秒。它们是浅层正确性及默认路由检查，不能为困难随机状态的完成率背书。[冻结输入和全部结果](benchmarks/htm-opt-2026-10-05/final-random.json.gz)

Ruff、`node tests/solver_ui.test.js`、Python 编译检查及 `git diff --check` 通过。原来一项取消测试要求“必须已生成节点”，但新版本可在初始上界进度事件就取消；已改为核对没有完成被中断层。较早测试失败记录保留。第一轮 HTTP harness 因基线子进程下相对输出路径错误而中止，没有可用矩阵行；修正绝对路径后从头运行全部 36 次，采用 `http-matrix-v2`，没有挑选或替换慢样本。[较早测试记录](benchmarks/htm-opt-2026-10-05/contracts.xml)、[中止的首轮 harness 记录](benchmarks/htm-opt-2026-10-05/http-matrix.json)。

原始基线是 `0079d26`，二进制 SHA-256 为 `47c7dc03a96f9c2529a6f301e285af8477b01461747928c8223f12861d423011`。HTTP 矩阵实测二进制为 `da415908a0e217b6db427de5c9f5f2bcf5de2719a10929e11716a260ddbe43ec`；源文件格式化后的最终本地二进制为 `12b448fa214370e3bd9f38e81e39c670e2a17e25a3c56ed1c2b3d0dbf6de44e9`。最终 Portable x64 O3/LTO、非 PGO 构建的 `.text` 和 `.rdata` 与 HTTP 实测版本逐字节散列一致；最终回归及无开关请求在该最终二进制上执行。新增 fast.cpp/fast.hpp 后，构建清单包含 14 个 C++ 源文件及头文件。[PE 段对照](benchmarks/htm-opt-2026-10-05/final-build-equivalence.json)

较大的新实验 JSON 以 gzip 无损保存，压缩后先逐字节解压核对再替换文件；原始字节大小和 SHA-256 全部保留，精简汇总仍是直接可读 JSON。用户提供的原评审及其诊断目录没有改写。[压缩清单](benchmarks/htm-opt-2026-10-05/evidence-compression.json)

**复现。** 从本项目根目录执行，基线源码和二进制在本轮本地 `.codex/htm-opt-2026-10-05/baseline-app` 与 `baseline` 下保留；换机器复现需从 `0079d26` 准备同样基线和资产。输出必须使用新路径，脚本拒绝覆盖证据。构建和离线准备之后，下面脚本分别重跑固定树、候选、36 请求矩阵和独立随机入口验证；矩阵约需十余分钟，后续结果不能自动沿用本轮数字。

```powershell
powershell -ExecutionPolicy Bypass -File native/htm/build.ps1
.venv/Scripts/python.exe -X utf8 release/prepare_runtime_caches.py --profile HtmFull
.venv/Scripts/python.exe -X utf8 tests/benchmark_htm_review_optimization.py incumbent --current native/htm/build/cube_solver_htm.exe --output .codex/htm-opt-rerun/incumbent.json
.venv/Scripts/python.exe -X utf8 tests/benchmark_htm_review_optimization.py pair --baseline .codex/htm-opt-2026-10-05/baseline/cube_solver_htm.exe --current native/htm/build/cube_solver_htm.exe --output .codex/htm-opt-rerun/same-tree.json
.venv/Scripts/python.exe -X utf8 tests/benchmark_htm_review_optimization.py candidate --current native/htm/build/cube_solver_htm.exe --output .codex/htm-opt-rerun/candidate.json
.venv/Scripts/python.exe -X utf8 tests/benchmark_htm_http_optimization.py --baseline-root .codex/htm-opt-2026-10-05/baseline-app --output .codex/htm-opt-rerun/http.json
.venv/Scripts/python.exe -X utf8 tests/verify_htm_review_random.py --output .codex/htm-opt-rerun/random.json
```

回归命令对应最终 109 项测试；首次采用默认六方向后也可单独运行最后两条前端及安装检查。

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest tests/test_htm_review_optimization.py tests/test_native_solver.py tests/test_htm_candidate_delivery.py tests/test_isolation_contract.py tests/test_search_lifecycle.py tests/test_hybrid_api.py tests/test_release_package.py tests/test_qtm_backend.py tests/test_qtm_speed_contract.py tests/test_two_by_two.py tests/test_tables.py tests/test_solver.py tests/test_runtime.py tests/test_version.py -q -p no:cacheprovider
node tests/solver_ui.test.js
.venv/Scripts/python.exe -X utf8 release/verify_installation.py .
```
