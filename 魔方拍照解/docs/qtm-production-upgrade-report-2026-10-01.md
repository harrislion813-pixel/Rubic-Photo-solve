# QTM 生产准备升级实施报告

日期：2026-10-01（Asia/Shanghai）。基线 HEAD：`931662805df003aeaeadad419fe10296961c94d2`。

按 [实施方案](qtm-production-readiness-plan-2026-10-01.md)完成首个工作包：环境与独立原生门禁、最小启动资产、候选先行与强表优先调度、完整校验提速、有界任务管理，以及实际 QtmStrong 包验收。**这是未发布的开发候选，应用版本仍为 1.9.0，QTM 保持实验状态。** 未提交 Git、未创建标签、未发布下载附件；没有用两个实拍样本代替普遍性能或目标硬件资格验证。

证据入口：[summary.json](benchmarks/qtm-production-upgrade-2026-10-01/summary.json)。本轮证据位于新目录，原方案与用户已有审查资料没有修改。

## 1. 来源和构建

- 修复本机可编辑安装元数据，源码与已安装分发版本均为 1.9.0；没有改回旧版本或改松版本断言。
- 保留旧 EXE、原始资产清单和未提交差异。旧 QTM EXE SHA-256：`e74002b9c7c03506d28d12ff2dc122cb95d904349666497253c605181f3316df`。
- 最终 QTM EXE SHA-256：`8c2912c43e267ea32ac9daea77902bc2258d91ef35f6a456e92c165734d5376a`。
- 最终构建为 GCC 16.1.0、Portable x64、O3/LTO、非 PGO；源码散列与 build-info、交付 EXE 相符。
- 7 项 QTM 目录 PDB 与原基线逐字节散列一致；没有转码、重建或扩大 strong / Tail。
- HTM 的 12 项原生源码/头文件未改变。因原目录缺少 build-info，打包器按已有流程重新编译了相同 HTM 源码，最终 SHA-256 为 `e6c0574cdecce36a30cfe572bb6a13a47228247c1fe05f520e77992d5f107797`。重建前的 HTM EXE 也已保留。

详见 [基线身份](benchmarks/qtm-production-upgrade-2026-10-01/baseline-identity.json)、[打包前身份](benchmarks/qtm-production-upgrade-2026-10-01/pre-package-identity.json)、[最终身份](benchmarks/qtm-production-upgrade-2026-10-01/final-identity.json)和 [包身份](benchmarks/qtm-production-upgrade-2026-10-01/package-identity.json)。

## 2. 实现内容

### 最小启动资产与完整校验

QTM 完整基础表有效时，先准备 QTM Corner、Phase-1 与候选表，不再主动映射私有 HTM Corner、Phase-1、Tail。缺失或校验损坏时，按需加载对应回退资产，并记录初始化错误和实际 profile。包内仍保留回退文件。309.24 MiB 是三项辅助文件字节，不当作工作集节省量。

v4 nibble 校验改为每块在局部结果中累计 checksum、范围和最大值，结束后再写入线程汇总。原来的逐字节 FNV 含义、全部 nibble 校验、块校验和、完整覆盖和最大距离校验均保留；不依赖 mtime 或清单存在来跳过数据验证。损坏的可选 strong / Tail 不会发布成有效快照，基础配置可继续使用。

额外保留 `legacy / fused / split` 扫描诊断方式。4 线程完整校验墙钟分别为 0.529 / 0.492 / 0.510 秒；差异较小，生产仍使用保持原始判断规则的 `legacy`。主要改善来自局部块结果，不能把这组单次测量写成 SIMD 或散列格式收益。`split` 的 checksum 工作线程累计约 1.827 秒、nibble 累计约 0.087 秒，两者不是墙钟。

记录坐标、主表、候选表、强表对称初始化、映射、完整扫描与辅助资产时间。映射调用时间不包含后续全部缺页成本；扫描包含按需分页。没有清空 OS 文件缓存，也没有独立冷磁盘缺页测量。详见 [扫描原始数据](benchmarks/qtm-production-upgrade-2026-10-01/loading-scans.json)。

### 候选先行与有界证明

- 默认 `CUBE_QTM_PROOF_SCHEDULE=strong-first`，强表加载期间基础证明累计窗口为 0.3 秒；窗口按低频检查点终止，允许小量调度超出。
- 候选器保持一个额度。校验配额默认最多 8 线程，并受请求总额度约束；1/2 线程不能等待一个无法获准加载的强表，采用明确基础或串行路径。
- 强表完整验证并发布后，从最后完整排除成本继续，保持最佳已验证候选与原绝对 deadline。中断窗口只记录丢弃量，不更新已完成成本，不签发该未完成层证明。
- 新强表在完整层边界采用时，重新运行原有方向决策；没有加入新的方向算法、剪枝或子树覆盖机制。候选线程绑定不可变 Phase-1 / Tail 指针。
- 不等待 Tail 才启动 strong 证明；Tail 按既有完整层边界采用并单独计时。暖 strong、缺表、拒绝接纳、校验失败均不进入无效等待。

保留回退开关：`CUBE_QTM_PROOF_SCHEDULE=overlap`、`CUBE_QTM_LOADER_THREADS=4`、`CUBE_QTM_REUSE=off`。完整强表 eager 启动脚本仍可选用，但本轮最终验收没有使用它或环境覆盖来获得性能结果。

### 后台任务与页面

QTM jobs 上限 100，清理完成的终态保留最多 600 秒，诊断事件和内存样本各保留末尾 64 项。尚未完成清理的取消任务不能被容量回收。等价活动状态、成本界、相同 timeout 共享任务和原期限；不同 timeout 创建独立任务，重试不延长期限。公开快照使用独立副本。

能力声明区分二阶、三阶基础/强资产，以及未验证文件、ready 和实际 adopted。二阶不依赖三阶 EXE/PDB，但仍需要 QTM 模块。页面按阶数控制入口，显示候选成本、真实已证下界、差值、校验/证明阶段和实际可用耗时，不显示虚假百分比。HTM 默认入口和求解路径保持不变。

## 3. 有限测量与失败原型

参考机：AMD Ryzen 7 9700X，8 核/16 逻辑处理器，32 GiB 内存，Windows 11 26200；请求总额度 15。搜索、构建和 pytest 没有同时进行。

### 源码 HTTP 对照

每配置只运行一次 initial-12，30 秒期限，新进程、关闭 resident 复用、100 ms 观察轮询，OS 文件缓存未清空。最终成本均为 20，并独立重放通过。

| 配置 | 首候选 | strong ready / adopted | 请求至清理 | 实际证明配置 |
| --- | ---: | --- | ---: | --- |
| 原始基线，staged | 1.531 s | 8.953 s / 未采用 | 17.500 s | base |
| A1/A2 首原型，旧扫描器，4 线程 | 0.875 s | 8.016 / 8.047 s | **18.219 s** | strong-no-tail |
| 局部块扫描器，4 线程 | 0.843 s | 2.000 / 2.031 s | 13.968 s | strong-no-tail |
| 同一扫描 EXE，8 线程 | 0.828 s | 1.734 / 1.765 s | 8.922 s | strong + Tail-8 |

首原型仅改善强表采用时点，没有改善总请求时间，原始结果保留，没有当作成功。扫描版本的 4/8 线程运行使用同一 EXE，但 Tail 是否及时采用、证明额度和找到解前的树也发生变化；不能把全部差值归因于校验线程数，不能宣称单位节点速度固定提升。

两次扫描 HTTP 使用中间 EXE `9b178d4d…`，不是最终 EXE。最终 EXE 增补可选损坏资产回退和小额度处理，其实际包结果见下一节，不拼接成一个加速比例。原始数据：[基线（归档）](evidence-archive-2026-10-06.md#file-06cc3d449bc1)、[失败首原型（归档）](evidence-archive-2026-10-06.md#file-a81ca1e7b020)、[4 线程（归档）](evidence-archive-2026-10-06.md#file-5b4d729db039)、[8 线程](benchmarks/qtm-production-upgrade-2026-10-01/scanned-strong-first-8-http.json)。

### 最终 EXE 的交错完整层

旧/最终 EXE 按 AB、BA、AB 顺序交错，两个固定状态各 3 次，每次最多 5 秒。相同完整资产、正向、无候选、无证明缓存、无节点 dual、strong-first 查询顺序。没有使用“找到解即停止”树来比较吞吐。

| 状态 / 请求界 | 旧 EXE 中位数 | 最终 EXE 中位数 | 差异 | 每次生成量 / completed_depth |
| --- | ---: | ---: | ---: | --- |
| pgo16 / 19 | 1.444785 s | 1.450297 s | +0.38% | 125,074,875 / 20 |
| known18 / 18 | 0.157937 s | 0.157628 s | -0.20% | 13,660,095 / 19 |

生成量完全一致，没有出现超过 5% 的退化，也没有达到值得宣称的热搜索加速。`completed_depth` 包含奇偶性排除成本，不代表额外搜索一层。先前非交错扫描版本数据仍保留，但不作为最终热收益结论。详见 [最终交错原始数据](benchmarks/qtm-production-upgrade-2026-10-01/final-fixed-pair.json)。全部固定层搜索累计仍在方案的 60 秒搜索预算内。

## 4. 最终候选包和真实页面

由当前源码构建一次 QtmStrong，压缩包 2,306,977,183 字节。ZIP SHA-256：

`fe660398348c36f9f2caa181e828042dfd91dec408912b78928588a15c5af480`

本机输出：`.cache/qtm-production/候选包/RubicPhotoSolve-1.9.0-QtmStrong-windows-x64.zip`。独立解压目录：`.cache/qtm-production/验收 魔方/RubicPhotoSolve`。两者都是本轮开发候选，不是已发布 1.9.0 的替换附件。

验收启动的是普通 `启动魔方求解器.cmd`，清除外部 QTM/native 环境覆盖，仅关闭自动浏览器弹出。逐项验证 19 项运行资产、原生构建来源和应用源码身份；页面来自打包 EXE，而非源码 server。每状态重新启动进程，上传原始六面照片并通过正常高级设置输入冻结 Facelets，正常选择 QTM、30 秒和点击求解。该流程验证照片渲染与已核对输入，不宣称自动识别对任意照片都准确。

| 实拍状态 | 后台首候选 | 页面首候选 | strong ready / adopted | Tail adopted | 请求至租约释放 | 页面严格确认 | 严格成本 |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| initial-1 | 0.922 s | 1.796 s | 1.781 / 1.797 s | 2.094 s | 16.172 s | 17.093 s | 22 |
| initial-12 | 0.828 s | 1.773 s | 1.719 / 1.734 s | 2.078 s | 7.656 s | 7.928 s | 20 |

两个首次候选成本均为 24，页面未把候选标成严格最短；最终动作与候选动作均由 Python cubie 模型独立重放并按 QTM 重算成本。strong ready 到 adopted 为 16 / 15 ms，低于 0.5 秒目标。基础窗口分别约 0.3001 / 0.3004 秒，旧 base 最后使用分别为原生搜索开始后 0.3115 / 0.3009 秒；各中断一次，丢弃生成量约 1,498 万 / 1,610 万，没有进入该层证书。

最终默认 bounded reuse 允许已暂停 resident 短暂保留，因此“租约释放”不等于全部映射已经解除。页面采用原有约 1 秒轮询，交付时间与后台生成时间分列；没有用额外高频 API 轮询取代真实页面。

Playwright 验证 1440×1000 和 390×844 两个视口：没有横向溢出、求解文本裁切或重叠，六个照片 canvas 均有非空多色像素，未发生页面 JS 错误。测试结束只关闭本次启动的进程树。详见 [页面原始事件（归档）](evidence-archive-2026-10-06.md#file-560817a6310f)、[桌面截图（归档）](evidence-archive-2026-10-06.md#file-92876ce15013)和 [手机截图（归档）](evidence-archive-2026-10-06.md#file-f387a295c34d)。

## 5. 正确性、隔离与 CI

| 门禁 | 结果 |
| --- | --- |
| 基础 Python / 实拍测试 | 77 通过，33 项明确不在此组运行 |
| 最终稳定 HTM / 共享分支覆盖门禁 | 74 通过，覆盖率 70.93%，超过原有 70% 门槛 |
| QTM、隔离、任务管理、生命周期、版本契约 | 46 通过 |
| QTM 最终原生门禁，含完整强表和损坏资产 | 19 通过，没有因缺资产跳过 |
| 追加有界原生复测，含 1/2/3 额度无期限浅态 | 13 通过，完整资产 6 项由上一行单独覆盖 |
| 重建 HTM 的有界原生回归 | 11 通过，两个深搜索测试未在此组运行 |
| Node 前端测试 | 4 个测试文件通过 |
| Ruff、全部 HTM/QTM C++ 格式、Git whitespace | 通过 |

原生 QTM 门禁包含独立四分之一转 BFS 的 1,195 个浅层状态、抽样最短成本/动作重放、半转成本为 2、partial 小表/缺表回退、三种完整块扫描规则、强表等待期间取消/期限/拒绝、1/2/3 总额度，以及完整 strong / Tail-8。截断、错误 metric、错误覆盖标记、错误块 checksum 与 eager 损坏五类资产均不能发布有效 strong 快照。浅层 oracle 不是任意新剪枝的普遍证明；本轮没有引入这类新剪枝。

真实生命周期检查使用两个不同浅状态而不是同状态证明缓存：热请求约 0.015 秒；未完成 loader 与完整 strong 的真实 TTL 分别约 20.266 / 20.406 秒。HTM 从 idle strong 和 BUSY/loader 抢占的附加等待约 0.250 / 0.187 秒。100 MiB 注入限额触发驱逐，进程故障后重建，旧 idle epoch / generation 不能关闭替代进程，最终 broker 的 active/resident/HTM holders 全部归零。详见 [生命周期证据](benchmarks/qtm-production-upgrade-2026-10-01/lifecycle.json)。

CI 增加独立 Windows Portable QTM 编译与有界原生测试。完整资产门禁由 `workflow_dispatch` 的 `qtm_full_assets` 显式启用，读取版本化缓存 `qtm-strong-v4-tail8-<version>-Windows`；缺必需表时失败而不是静默 skip。普通提交不重新建巨型表，稳定 HTM 覆盖范围不变。**本机门禁已运行；远端 CI 尚未提交/触发，完整缓存尚需由发布流程提供。**

保留失败证据：环境版本未修复前的 XML、首调度原型、早期原生测试中的协议字段断言错误，以及生命周期脚本第一轮结果。测试脚本修正了 Windows 浮点期限比较、build-info SHA 大小写比较和驱逐清理完成屏障。交错探针首次启动只完成初始化，因为误读现有 `case_state` 的二元返回值而失败，未执行搜索；其空运行记录保留在 `final-fixed-pair-preflight.json`，未计入性能样本。

## 6. 后续条件与复现

首个工作包达到本机两个实拍的快速候选、及时强表采用与 30 秒严格完成目标，固定层没有退化，因此不立即引入第二阶段的子任务迁移/覆盖账本。热搜索专门化、selective dual、Portable PGO、互补 PDB 和更大 Tail 均未开展，也未进入生产默认。

正式调整 QTM 状态或宣传广泛性能前，仍需最终包上独立冻结的 12 状态资格集、新旧同机配对、超时/PAR-2 调查以及另一目标 x64 硬件验证。单次新进程、暖 OS 文件缓存的结果不能当作总体成功率、p95、冷磁盘性能或任意魔方 30 秒保证。

以下在项目根执行；属于复现入口，不要求日常重复全部性能运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_qtm_backend.py tests/test_qtm_speed_contract.py tests/test_isolation_contract.py tests/test_search_lifecycle.py tests/test_version.py
$env:REQUIRE_QTM_BINARY='1'
$env:REQUIRE_QTM_STRONG='1'
.\.venv\Scripts\python.exe -m pytest -q tests/test_native_qtm.py
.\.venv\Scripts\python.exe tests/check_qtm_speed_reuse.py --output .cache/qtm-production/lifecycle.json
.\.venv\Scripts\python.exe tests/benchmark_qtm_production_pair.py --baseline .cache/qtm-production/baseline/cube_solver_qtm.exe --current native/qtm/build/cube_solver_qtm.exe --output .cache/qtm-production/final-fixed-pair.json
.\release\build_windows.ps1 -Profile QtmStrong -OutputDirectory '.cache/qtm-production/候选包' -SkipTableBuild
```

实际包页面验收入口为 `tests/accept_qtm_production.py`，参数为 `--archive`、独立 `--destination`、`--node`、`--playwright` 和 `--output`。浏览器运行时通过 Codex 的 workspace dependencies 提供；无需把 Playwright 加入应用运行依赖。重复验收应选择新解压目录，不沿用另一构建的旧目录。
