# HTM 回退与 QTM 隔离实施报告

后续复审修复与固定完整层诊断见 [QTM 隔离复审修复与短验收](htm-qtm-isolation-followup-report.md)。下文保留原 `b68da78` 的实施与最终 ZIP 记录；其中性能结论的适用范围以后续报告为准。

日期：2026-09-30。实施分支：`codex/htm-rollback-qtm-isolation`。本报告对应本地版本 `1.8.0`，没有远程发布或改写原有历史。验收范围遵循[实施方案](ai-htm-rollback-qtm-isolation-plan.md)第 5 节；用户要求缩短验收后，没有再增加长求解。

## 结论

| 项目 | 结论 |
| --- | --- |
| HTM 恢复 | **通过。** 完整应用链取自 `ae73ca81af1ed077c059f3345377190bf0ce2882`（1.4.0）；独立 HTM 引擎在同资产、同编译模式、15 线程下通过正确性与性能门槛。`HtmFull` 最终包解压后实跑通过。 |
| QTM 迁移 | **功能与隔离通过，性能保持实验状态。** 冻结来源为 `c01d90dcbc449faf3b6128020e71655a0a47960b`。最终 `QtmStrong` 包的两组实拍均得到严格证明，但响应时间较 Q0 增长；未将它作为替代 HTM 稳定包的条件。 |
| 发布 | 已生成本地可运行 `HtmFull` 和 `QtmStrong` ZIP，均在仓库外的独立目录解压、校验清单并运行。默认 CI 显式构建 `HtmFull`；QTM 强包需显式选择。 |

## 来源、现场与架构

开始前保留了原主工作区的未提交 `README.md`、历史 EXE、build-info 及 Git 外大资产，使用两个托管隔离工作区分别读取 H0 与 Q0。原主工作区状态没有被重置；其原有三项变更仍在。冻结摘要见[基线清单](benchmarks/htm-qtm-isolation-baseline-manifest.json)，原 `README.md` 改动另存为[补丁](benchmarks/pre-isolation-readme.patch)。用户实际安装的旧包未提供，故不能断言它与仓库构建完全相同。

H0 的 C++ 求解文件保存在 `native/htm`；除独立构建脚本外，核心文件与来源字节一致。Q0 的 C++ 文件保存在 `native/qtm`，仅服务入口 `main.cpp` 为专用 QTM 能力声明及拒绝 HTM 请求而调整；源文件核对见[审计结果](benchmarks/frozen-native-source-audit.json)。两者分别构建 `cube_solver_htm.exe` 和 `cube_solver_qtm.exe`，各有源码、进程、资产根、坐标缓存、候选器和 Python 回退。HTM 使用旧协议 v2 适配器；QTM 使用自身协议 v3。统一 metric、动作重放、结果与证明语义只发生在 `cube_app/solvers` 请求边界。没有在同一个 `NativeOptimalSolver` 中继续添加 metric 分支。

QTM 默认惰性导入、按请求启动，HTM 请求不预热 QTM 强资产。资源分配器将高负载证明限制为每次一个、使用与旧应用相同的本机生产额度 15 线程；HTM 到来时取消 QTM 并让出额度。QTM 请求结束后退出 QTM 原生进程以释放大表，而不是让空闲的独立进程继续占内存。QTM 原生故障转入其私有 Python 回退，不重启 HTM。页面切换 metric 时清除上一种 metric 的最短证明，候选可执行与严格证明分别标记，超时或取消不产生证明；QTM 不复用 HTM 的最短标记。

迁移保留了 Q0 仿射坐标、合法下界、精确 nibble 强表、Tail 和原生候选成果。未据局部微基准改动其剪枝或坐标规则，因此本轮没有扩充 oracle 集。

## 配置与资产

所有最终对照使用 16 逻辑处理器机器上的 **15 个原生工作线程**。最早的冻结清单暂记 4 线程，且 `htm-h0-real.json` 的 runner 元数据也写了 4；旧应用实际按 `min(32, cpu_count - 1)` 传入 15，其原生进度帧也有 15 个 worker。此项已在[配置更正](benchmarks/acceptance-config-correction.json)与[原始帧审计](benchmarks/real-thread-audit.json)登记。最早的 4 线程短测保留供追溯，不用于最终性能判定。H0/H1 使用相同 native O3 模式；Q0/Q1 使用相同 portable O3 模式，各组旧新版资产 hash 相同，详见[资产逐项比对](benchmarks/packages-same-assets.json)和四份 build-info。

`HtmFull` 清单显式包含完整 HTM 主 PDB 与 Tail-6；`QtmStrong` 清单另显式包含 QTM 基础、强表和 Tail，两个引擎资产各归各目录。[HtmFull 清单](benchmarks/HtmFull-asset-manifest.json)核验 7 项，[QtmStrong 清单](benchmarks/QtmStrong-asset-manifest.json)核验 19 项。原默认 CI 既未启用 QTM 资产也未附带 HTM Tail-6，现以 `-Profile HtmFull` 明确稳定包内容，强包以 `-Profile QtmStrong` 显式构建。`CiMinimal` 只跳过 Tail，仍构建完整主 PDB，不能描述为只建浅层表。打包前检查 PDB 头、metric、完整标记和散列；Python 缓存预建到各自包内。解压验收使用独立 Unicode 目录，不从仓库 `.cache` 补资产。

## 缩小后的验收结果

八个固定浅层状态在 H0、H1、Q0、Q1 的最终解压包中均通过：动作重放回复原态、按各自 metric 的代价正确，最短标记与独立小深度 Dijkstra 精确值一致。实拍仅检查 `initial-1` 和 `initial-12`：四包的照片 API 与浏览器颜色分类结果均匹配冻结参考；只为第 12 组补充六面参考标注和[人工核对网格](benchmarks/initial12-reference-grid.png)，没有要求或声称识别全部 16 组。

短诊断每状态 3 次、单次上限 5 秒，表中为响应中位数。`pgo16`、`known18` 均使用旧新版相同的成本界、资产、编译模式与 15 线程。完整排除层及节点统计在原始 JSON 中；所有未完成层、预算耗尽状态仍按原值保存。

| 引擎 / 状态 | 旧版中位数 | 新版中位数 | 结果 |
| --- | ---: | ---: | --- |
| HTM `pgo16` | 0.263 s | 0.293 s | 初测 +11.4%；定点成对复测 0.245 / 0.234 s（新版 -4.1%）。该状态很短，波动可见。 |
| HTM `known18` | 1.202 s | 1.241 s | +3.3%；成本 16 完整排除，两版均生成 201,407,415 个候选。 |
| QTM `pgo16` | 1.521 s | 1.518 s | -0.2%；同界预算耗尽，均只承认完整成本层，不把未完成层当证明。 |
| QTM `known18` | 1.139 s | 2.571 s | +125.7%；定点复测 0.889 / 1.433 s（+61.2%）。完整成本层均一致，但墙钟不达标。 |

最终实拍每状态、每引擎、每版本只运行一次，单次上限 180 秒。下表为**用户请求到完成**的墙钟，均来自独立解压包。`cost` 是该 metric 的严格最短代价，候选动作已重放验证；原始记录同时保留首次候选、完成层及超时字段。一次结果只能证明这两例的本机表现，不能推广为总体加速。

| 引擎 | 状态 | 冻结旧版 | 隔离新版 | 严格最短代价 | 判定 |
| --- | --- | ---: | ---: | ---: | --- |
| HTM | `initial-1` | 30.498 s | 22.258 s | 18 | 新版 -27.0%，通过 |
| HTM | `initial-12` | 4.811 s | 4.844 s | 17 | 新版 +0.7%，通过 |
| QTM | `initial-1` | 21.868 s | 28.782 s | 22 | 新版 +31.6%，实验状态 |
| QTM | `initial-12` | 6.125 s | 19.020 s | 20 | 新版 +210.5%，实验状态 |

QTM 新版账本显示两次请求的队列时间均为 0，强表 ready 约 8.97 / 8.73 秒，首次候选约 9.00 / 8.77 秒，证明墙钟约 28.28 / 18.66 秒。Q0 的第二个请求在常驻进程中复用已加载资产，新版按释放策略再次冷启动；**结合进程生命周期和账本，这可能解释部分端到端退化**，但短测 `known18` 也出现变慢，不能将全部差距归于启动。下一轮若继续 QTM，应首先依据此账本评估强表加载和资源释放策略，再针对同界搜索的剩余差距排查；不得以延迟释放破坏 HTM 优先权。此轮没有据此改搜索算法或扩大验收。

生命周期短检覆盖：仅 HTM 包中 QTM 返回不可用、二阶与三阶 HTM 简单请求、QTM 初始无进程且请求后释放进程、QTM→HTM 取消让出、QTM 故障后的私有 Python 回退与 HTM 继续可用。QTM→HTM 的端到端 HTM 响应约 2.34 秒且无 `yield_fault`；该数字含 HTM 启动与求解，**不能单独证明让出附加延迟达到 1 秒目标**。不把这项未隔离测得的目标写成通过。

## 本地交付物

| 包 | 最终 ZIP | SHA-256 | 解压后可运行 EXE |
| --- | --- | --- | --- |
| 稳定 HTM | `dist/HtmFull/RubicPhotoSolve-1.8.0-HtmFull-windows-x64.zip` | `e7b203e8ef3598987861a3fef5ba25ef17a5b8256f8a42cd4ccfb570fd6ebbf7` | `C:\Users\harriron\Desktop\魔方隔离验收\H1-ui\RubicPhotoSolve\RubicPhotoSolve.exe` |
| 含实验 QTM | `dist/QtmStrong/RubicPhotoSolve-1.8.0-QtmStrong-windows-x64.zip` | `977d2d73ae3dad4c80bb9b20bea3f6f610821e34cae1b344844b9422433ee54d` | `C:\Users\harriron\Desktop\魔方隔离验收\Q1-ui\RubicPhotoSolve\RubicPhotoSolve.exe` |

两包均从最终 ZIP 解压后完成资产清单核验、照片输入与严格求解。`HtmFull` 不包含 QTM EXE 或资产；`QtmStrong` 提供明确的实验 QTM 入口。历史 H0/Q0 包与其 hash 保留在原始运行记录中。包是本地可运行交付物，未上传或远程发布。

## 原始记录与复现入口

- 冻结和构建：[基线清单](benchmarks/htm-qtm-isolation-baseline-manifest.json)、[源码审计](benchmarks/frozen-native-source-audit.json)、[线程更正](benchmarks/acceptance-config-correction.json)、[资产比对](benchmarks/packages-same-assets.json)、`benchmarks/{h0,h1,q0,q1}-build-info.json`、`benchmarks/{htm,qtm}-final-package-build.log`。
- 照片与浅层：`benchmarks/{htm-h0,htm-h1,qtm-q0,qtm-q1}-{photos,shallow}.json`；第 12 组参考保存在 `../tests/initial_solver_cases.json`。
- 15 线程短诊断：`benchmarks/{htm-h0,htm-h1,qtm-q0,qtm-q1}-short-15.json`；定点复测分别为 `htm-{h0,h1}-pgo15-retest.json`、`qtm-{q0,q1}-known15-retest.json`。早期 4 线程文件、校准和其余定点记录原样保留，判定以本节指定文件为准。
- 最终实拍：[H0（归档）](evidence-archive-2026-10-06.md#file-a21a7fa56ecd)、[H0 严格验证补记](benchmarks/htm-h0-real-verification.json)、[H1 最终包（归档）](evidence-archive-2026-10-06.md#file-0887516df3ad)、[Q0（归档）](evidence-archive-2026-10-06.md#file-bb894e74406d)、[Q1 最终包（归档）](evidence-archive-2026-10-06.md#file-83fb8e9e8477)。中途 H1/Q1 包记录保留作异常调查史，不用于最终对照。
- 生命周期：[仅 HTM 包](benchmarks/htm-only-lifecycle.json)、[QTM 包按需进程](benchmarks/qtm-package-lifecycle.json)、[API 取消与故障](benchmarks/isolation-api-lifecycle.json)。运行脚本在 `tests/accept_*.py`、`tests/benchmark_isolation_short.py`、`tests/check_isolation_api.py` 等文件中；包构建及资产检查在 `release/`。

静态检查、Python 编译、页面 Node 测试、原生二进制测试 6 项、Python 求解与二阶测试 13 项及 PowerShell 脚本解析已通过。验收没有运行旧 48+32 集合、额外随机集、全部 16 组照片、多线程矩阵或重复长测试。
