**HTM / QTM 下一步速度优化实施报告 · 2026-10-03**

本报告对应[2026-10-02 执行方案](htm-qtm-next-speed-plan-2026-10-02.md)，完成首轮 P0、H1、H2、Q1、Q2 实施和正式 72 请求验收。HTM 首候选交付中位数下降 50.61%–62.31%，但 initial-12 严格完成出现可重复退化；QTM 实验包 PAR-2 均值下降 21.71%，但 initial-2 出现可重复退化。按冻结门槛，两个引擎均不采用本轮速度变体的默认配置。H2、Q2 同样不启用。

已构建独立的保守默认包：HTM 在候选预算结束后发布最佳结果，QTM 使用 generic，保留观测、取消/额度保护和 QTM 初始化暂停修复。该包完成 8 次正常页面功能检查与公式回放；其中 current 的 HTM initial-1 仍超时，不能宣称它已通过完整速度门槛。72 次性能数字属于另行冻结的 H1/Q1 实验包，不能移植为保守默认包的收益。Portable PGO 仅补齐构建与训练支持，本轮未训练或测试；P2 未展开。

以下数字来自[有效原始矩阵](benchmarks/next-speed-2026-10-02/formal-final/formal-matrix.json.gz)、[原汇总](benchmarks/next-speed-2026-10-02/formal-final/summary.json)、[补齐下界的独立汇总](benchmarks/next-speed-2026-10-02/formal-final/summary-with-bounds.json)和[工作包记录](benchmarks/next-speed-2026-10-02/work-package-results.md)。中断、方法无效和测试配置失败的原始记录均保留。

| 工作包 | 已完成范围 | 最终决定 |
| --- | --- | --- |
| P0 身份与计时 | 原始冻结、受控基线、实际包身份、候选/终态/内存/额度观测与 72 请求 | 完成；原冻结副本与失败记录保留 |
| P0 六组照片 | initial-1、12、2、5、8、16 的独立人工参考、36 张原照片与 Facelets 身份、实际页面核对 | 六组自动识别匹配参考，实际逐块/旋转修正均为 0 |
| H1 | 提前发布实现、合法重放、单调上界、旧回调保护、绝对 deadline、共享额度 | 交付目标通过，initial-12 严格中位数 +174.64%；默认关闭，保留显式开关 |
| H2 | 固定数组 + stable_sort；固定数组 + 稳定插入排序 | 两变体均拒绝，保留原容器/排序 |
| Q1 | 完整 QTM strong 专用热路径，通用回退保留 | 同树层改善 28.96% / 28.35%，完整请求 initial-2 中位数 +47.49%；默认 generic，专用路径仅显式启用 |
| Q2 方向短片 | 同总预算的 legacy / short-slices 独立对照 | 没有降低最终上界，默认保留 legacy |
| Q2 late Tail | 一次、最多 0.2 秒、沿原 deadline 的局部改进；真实生产桥接 12 次 AB | 实际改进为 0，默认保持 off |
| P1 | 两引擎 Portable PGO 调用链、独立训练集及排除检查 | 仅支持就绪；未训练、未构建 PGO、未作性能对照 |
| P2 | 更大表、额外剪枝、任务粒度等算法扩展 | 延期；本轮未执行 |

**原冻结身份与受控基线的区别**

[baseline-identity.json](benchmarks/next-speed-2026-10-02/baseline-identity.json) 冻结原执行起点：HEAD `6754a8c2cb9b87860f594bba0d59326ef260aceb`、版本 1.10.0、Windows 11、16 逻辑 CPU、15 个总额度。原冻结副本 `.codex/next-speed/baseline` 不修改。原 HTM EXE SHA-256 为 `e6c0574cdecce36a30cfe572bb6a13a47228247c1fe05f520e77992d5f107797`，原 QTM 为 `8c2912c43e267ea32ac9daea77902bc2258d91ef35f6a456e92c165734d5376a`。编译条件为 Portable x64、普通 O3/LTO、非 PGO；大资产和缓存另有原始内容散列。

默认请求的受控对照另外位于 `.codex/next-speed/baseline-observed`。[身份差异](benchmarks/next-speed-2026-10-02/controlled-baseline-identity.json)、[可审查 patch](benchmarks/next-speed-2026-10-02/controlled-baseline.patch) 和[验证报告](benchmarks/next-speed-2026-10-02/controlled-baseline-verification.md) 明确列出真实改动：首次审计重算原冻结副本 335 个已复制文件，零差异；独立副本有 8 个源码文件的 P0/资源适配，以及一个新增 mock 测试文件。原始 EXE 对照和受控 EXE 对照不能混称为同一二进制。

受控 HTM 保留原候选算法与最多 1.5 秒改善预算，观察回调只记录首解/改进，不发布；预算结束后才更新 job/incumbent 和原 HTTP 分支。它没有引入 H1 的提前交付、候选启动时 incumbent 刷新或搜索取消算法改造。去掉观测脚手架后，候选搜索 AST 与冻结版一致；QTM bridge 去掉客户端终态观测后 AST 一致；HTM C++ 去掉层边界额度/线程遥测后搜索源码逐字一致。H2、Q1、Q2、PGO 不进入这份算法对照。

统一资源约束是有意改动：15 总额度中候选占 1、证明初始占 14；候选结束后允许在后续完整层边界恢复 15，活动层不扩线程。候选未开始时也预留这 1 个额度；总额度 1 时候选、证明串行，仍使用原绝对 deadline。候选只能持有本 job 的 proof lease，proof slot 等已启动候选结束后才放行下一个 job；queued 请求取消可以退出等待。Python fallback 同样受该上限约束。H1 和对照均使用此约束，不能用多线程超额解释交付或搜索改善。

HTM `terminal_seconds` 从 `/api/solve` 原入口计时，在后台终态确认时冻结，候选退出、资源释放和 UI 轮询延迟另报。QTM 记录原生终帧到达客户端的 `client_terminal_at`，验证成功且 `optimal=true` 后才有 `strict_confirmed_seconds`。两引擎保留真实候选/终帧、完整层、采用事件和原绝对期限。HTM 内存字段是 native 单进程生命周期峰值；矩阵另用相同外部 OS 观察器核对两个版本，不能与进程树同时工作集之和混算。

[受控基线 21 项门禁](benchmarks/next-speed-2026-10-02/controlled-baseline-contracts.xml) 通过，主要是 mock、AST 和桥接合约，`actual_solver_calls=0`。另有 Windows 当前进程内存 API 烟测。实际包曾完成[身份核对及两个新进程浅状态烟测](benchmarks/next-speed-2026-10-02/controlled-baseline-package-identity.json)：HTM 复用全部 12 个 C++ 源 SHA 与 observed 相符的 Portable 构建 `f85a87aca23957fdca40e5c677b366d8713dc943612dd6cdb4df891ba587338f`，QTM 保留原冻结 EXE；五个关键 Python 模块均打包自 observed。两度量对一个 R 动作均严格完成成本 1，独立重放正确，实际 terminal/events/额度字段可用。这是后续初始化资源修复前的包证据，不能替代修复后的重新构建身份或最终包验收。

**六组照片、合法状态与识别范围**

[照片参考说明](benchmarks/next-speed-2026-10-02/photo-reference-notes.md) 和[人工参考](benchmarks/next-speed-2026-10-02/manual-photo-reference.json) 固定 `URFDLB`、原照片朝向和逐行九宫格。1、12 保留原参考，2、5 独立视觉复核历史标注，8、16 从无分类标签的原照片/网格独立读色后冻结，未把分类器输出当真值。36 张照片、浏览器缩放/透视预览、Facelets 的 SHA 及参考来源见 [initial_solver_cases.json](../tests/initial_solver_cases.json)。反光歧义均已记录并解决。

[实际页面识别](benchmarks/next-speed-2026-10-02/photo-recognition.json) 六组均与人工参考一致，逐块修正和面旋转修正都为 0，求解接口被拦截且请求数为 0；没有为识别核对运行性能搜索。[独立合法性记录](benchmarks/next-speed-2026-10-02/photo-legality.json) 检查角/棱集合、朝向和、翻转和、奇偶性和 Facelets 回环。[真实 Canvas 色块回归](benchmarks/next-speed-2026-10-02/browser-patch-color-regression.json) 全部通过，并记录 36 张预览散列。

识别耗时来自普通上传核对过程，未在性能独占窗口采集，不纳入求解加速。正式页面矩阵仍上传原照片，同时明确记录高级 Facelets 输入覆盖，算法比较采用同一份冻结状态。原已知最优成本作为回归 oracle：initial-1 / 12 的 HTM 为 18 / 17，QTM 为 22 / 20。有效矩阵中新旧版本分别严格确认 initial-2 / 5 的 HTM 成本 17 / 17，以及 initial-2 / 5 / 8 / 16 的 QTM 成本 21 / 22 / 20 / 21；这些是本轮输出，冻结用例中的新增状态 `known_optimal_costs` 仍保留 null，没有反填为独立 oracle。HTM initial-8 / 16 本轮未证明最短。

**H1 交付实验与默认回退**

Python HTM 候选器发现首次解和更短解后立即回调；H1 实验模式验证动作合法、可复原、HTM 成本正确才提前发布单调 incumbent。原生证明和候选原本已重叠，改动缩短的是已发现候选的发布等待。请求取消、完成、过期或被新 job 替换后，旧回调不能更新结果；首次 HTTP 响应发出后，后台改善仍受候选额度和原 deadline 限制。冷表加载/构建和串行小额度路径也沿用同一预算。

[H1 53 项合约](benchmarks/next-speed-2026-10-02/htm-h1-final-contracts.xml) 和[真实原生动态额度记录](benchmarks/next-speed-2026-10-02/htm-h1-dynamic-gates.json) 覆盖 1/2/3 额度、取消、恢复、浅状态复用以及终态保护。旧阶段的 [78 项 Python 契约](benchmarks/next-speed-2026-10-02/final-python-contracts.xml) 与[原日志](benchmarks/next-speed-2026-10-02/final-python-contracts.log) 保留 0 fail/skip 和 1 个 pytest cache 写入权限警告。这只是该时间点的 Python 范围；新 C++ 资源修复另有真实门禁，默认开关回退另有最终 80 项合约，均在后文分别列出。

正式矩阵六状态的页面首候选中位数全部改善超过 20%，但 initial-12 严格完成的三次配对有两次退化超过 5%，整体 HTM PAR-2 也未达到 15% 目标。因此最终 `CUBE_HTM_EARLY_CANDIDATE` 默认 off，设置为 `1` 可显式实验。默认只在候选器返回预算内最佳解后发布一次，仍保留后台任务、job 所有权、取消与额度改进；它恢复的是发布策略，并非把整个 server 字节还原为原版本。

**H2 拒绝、Q1 单项通过但不采用默认**

完整排除层实验固定相同度量、资产、方向、15 线程、成本界和无候选/无证明缓存条件，每版本每状态三次，顺序 AB、BA、AB。原始数据分别见 [H2 stable](benchmarks/next-speed-2026-10-02/h2-fixed-stable.json)、[H2 insertion](benchmarks/next-speed-2026-10-02/h2-fixed-insertion.json)、[Q1](benchmarks/next-speed-2026-10-02/q1-pair.json)。

| 变体与状态 / 成本界 | 原基线墙钟中位数 / 秒 | 变体 / 秒 | 相对变化 | 判定 |
| --- | ---: | ---: | ---: | --- |
| H2 固定数组 + stable_sort · legal-20260927-0 / 16 | 1.417043 | 1.483574 | +4.70% | 拒绝 |
| H2 固定数组 + stable_sort · known18 / 16 | 1.429353 | 1.456929 | +1.93% | 拒绝 |
| H2 固定数组 + 稳定插入排序 · legal-20260927-0 / 16 | 1.534990 | 1.562112 | +1.77% | 拒绝 |
| H2 固定数组 + 稳定插入排序 · known18 / 16 | 1.489930 | 1.515139 | +1.69% | 拒绝 |
| Q1 full-strong · pgo16 / 19 | 1.612170 | 1.145269 | −28.96% | 通过单项门槛 |
| Q1 full-strong · known18 / 18 | 0.178112 | 0.127626 | −28.35% | 通过单项门槛 |

H2 两层完整生成量分别为 `194928936` / `201407415`，Q1 为 `125074875` / `13660095`，新旧各自相同，各类拒绝量一致。查询数含动态任务重检，范围单列，不当作唯一生成量。H2 stable 的原检查因 phase1 查询数不完全相等而失败，原 `summary` 为空、没有 `adopt` 字段，仍保留该失败；表中中位数是已保存原始墙钟的静态汇总，不是重跑后改写通过。两 H2 变体本身都没有达到至少 5% 改善，因此生产保留原容器与排序。

Q1 在层入口持有不可变资产快照，完整 QTM strong + 默认 strong-first、dual off、prefetch off、slice keep 才选择专用路径，拒绝节点仍延迟不必要坐标展开，接受节点保留后续递归所需字段。完整、部分、缺表、损坏资产及实验配置保留 generic 回退。[Q1 最终 15 项](benchmarks/next-speed-2026-10-02/q1-gates-final.xml) 和[QTM 38 项](benchmarks/next-speed-2026-10-02/qtm-final-gates.xml) 均通过、无 skip；后者早于随后 Tail 末端取消检查和当前资源修复，不能冒称覆盖未来源码。Q1 EXE 的单项身份为 `18b45f69ae55d7eb44e245aeb31929080e226c344edf149828e9bfcdc5d9d823`，不与后来合并包 EXE 混用。

完整请求矩阵的 QTM initial-2 有两次配对退化超过 5%，不能用全六状态均值下降抵消。因此最终 Python bridge 与 C++ `SolverOptions` 均默认 generic；`CUBE_QTM_EXPANSION=full-strong` 或原生 `--qtm-expansion=full-strong` 才启用专用路径。完整层的单项收益保留为实验结果。

**Q2 两项均不改默认**

[方向短片实验](benchmarks/next-speed-2026-10-02/q2-candidate-schedule.json) 为两状态 × 两调度 × 三次，共 12 请求，每次候选总预算 3 秒、候选额度 1。initial-1 的 legacy / short-slices 首候选中位数为 0.0545003 / 0.0489799 秒，initial-12 为 0.0423706 / 0.0422331 秒；两个版本全部最终成本 24，没有改善上界，也没有完整请求收益证据，保留 `legacy` 默认。

late Tail 通过[真实 C++ harness 门禁](benchmarks/next-speed-2026-10-02/qtm-tail-gates.xml)，验证一次尝试、真实替换、1/2/3 额度、取消和原 deadline，但 harness 的测试协调等待不能作为产品速度。[生产桥接 12 次 AB 原始记录](benchmarks/next-speed-2026-10-02/q2-late-tail-production.json) 与[固定日志](benchmarks/next-speed-2026-10-02/q2-late-tail-production.log) 使用 EXE `9f71a1b72b4fb43f3079f4027435253872c741bff6b57ac62530303d3eb5795f`、新原生进程、真实 managed-loader 准入、15 总额度、默认 staged、原 30 秒期限，无已知 incumbent 注入。

| 状态 | off / on 请求中位数 / 秒 | on/off | on 尝试次数 | 实际改进 |
| --- | --- | ---: | --- | --- |
| initial-1 | 24.578 / 17.578 | 0.715192 | [1,1,1] | [0,0,0] |
| initial-12 | 11.344 / 8.250 | 0.727257 | [0,0,0] | [0,0,0] |

12 次全部严格完成，最终成本分别 22 / 20，无新超时；启动、strong/Tail 准入与采用、额度、候选/终态重放均有记录。raw 中 78 条含公式事件独立重放并重算 QTM 成本无错误，这个 78 是公式事件数，与前述 78 项 Python 契约是两种口径。off/on 的原生进程工作集峰值基本一致。

该变体默认保持 `off`。initial-1 真实尝试三次均未降低上界，initial-12 的 on 从未运行 late Tail，却呈相近中位数比；因此表面约 28% 下降不能归因于 Tail。保留所有三次与明显离散，不将 staged 采用时点/展开量变化包装成同树收益，也不把两状态 AB 合并进六状态正式矩阵。

**资源修复与验收脚本修复**

QTM 在原冻结基线中已有 Symmetry 初始化缺少暂停 checkpoint 的问题：浅请求结束时，loader 可能仍在初始化段，不能及时响应 pause，客户端按原资源 watchdog 执行 fail-close。[原资源失败](benchmarks/next-speed-2026-10-02/qtm-bounded-reuse-final.log)保留，失败时 Q1 strong 展开和 Q2 Tail 尝试均为 0。修复仅修改 `native/qtm/include/symmetry.hpp`、`src/symmetry.cpp` 和 `src/strong_coords.cpp`：构造函数接受可选检查回调，SortedSliceSymmetry 把它透传到 Phase1Symmetry 成员构造，并在有界初始化循环内低频检查。搜索热路径、资源准入、500 毫秒原生暂停窗口、800 毫秒客户端等待和请求期限均不改。

资源修复只进入 current；受控 baseline 继续使用原 QTM EXE，原冻结副本不变。[修复后的 3 项真实门禁](benchmarks/next-speed-2026-10-02/qtm-loader-repaired-gates-final.xml)通过、无 skip：实际成员初始化暂停、执行数归零、恢复完成、回调与无回调坐标等价、暂停中取消不签证明、EOF 恢复并 join。[19 项资产/期限门禁](benchmarks/next-speed-2026-10-02/qtm-loader-repaired-assets.xml)通过、无 skip，覆盖完整/部分/损坏/缺失资产和 1/2/3 额度。最初协议测试遗漏 base 资产的配置失败另保留在 `qtm-loader-repaired-gates.xml`，修正配置没有改变生产代码。

[修复后的 bounded reuse 原始结果](benchmarks/next-speed-2026-10-02/qtm-bounded-reuse-repaired.json)及[日志](benchmarks/next-speed-2026-10-02/qtm-bounded-reuse-repaired.log)通过未完成加载的两个不同浅状态复用及真实 20 秒 TTL、完整 strong/Tail 的 20 秒 TTL、旧 generation/idle epoch 保护、HTM 优先抢占、强制内存回收和故障进程替换。最后 broker 的 active/resident 均清空。这些实证晚于 78 项 Python 契约，覆盖新 C++ 修复。

资源修复后的 H1/Q1 实验 `QtmStrong` 包位于 `dist/next-speed-2026-10-03-loader-repaired/RubicPhotoSolve`，ZIP 含 153 文件、2,307,013,732 字节，旧包保留。构建日志为[实验包日志](benchmarks/next-speed-2026-10-02/current-loader-repaired-package-build.log)。[实验源码/EXE/资产身份](benchmarks/next-speed-2026-10-02/current-final-identity.json)记录 QTM EXE SHA `38ee262a42246265dc40e5430057c279c60d156b5bcb82286a2727d78fe41ca8`，HTM 为 `f85a87aca23957fdca40e5c677b366d8713dc943612dd6cdb4df891ba587338f`；两者均 Portable O3/LTO、非 PGO。17 个资产/缓存文件与原冻结相同。这是正式 72 请求所测的实验身份，最终保守默认包另有独立身份，不能覆盖或混用。

Windows 文件共享影响了第一次正式初始试跑：普通 `Get-Content` 读句柄可能阻止原地 JSON 写入，响应监听器保存失败被误记为页面错误。已停该尝试并保留[原始 JSON](benchmarks/next-speed-2026-10-02/formal-matrix-file-sharing-attempt.json)、[日志](benchmarks/next-speed-2026-10-02/formal-matrix-file-sharing-attempt.log) 与[方法说明](benchmarks/next-speed-2026-10-02/file-sharing-attempt-methodology.json)，其中两个 HTM 超时和原公式/终态仍保留，没有按速度删掉慢记录。

验收脚本改为完整临时 JSON + 异步原子替换，仅在 case 边界保存，临时共享锁有界重试，持久化异常与页面异常分开；最终无法提交时保留完整 uncommitted checkpoint 并失败。正常页面一秒轮询、已采集响应时间和原 deadline 不因脚本修复改变。参见[验收脚本说明](htm-qtm-next-speed-harness-review.md)。这次有记录的复测用于已声明的外部干扰；不可反复复测直到结果好看。

正式计时期间不并行构建、测试、另一引擎或全资产散列。只读观察使用 `FileShare.ReadWrite | FileShare.Delete` 获取字节快照并关闭句柄，再解析，不高频解析不断增长的矩阵。有效报告已核对完整 72 条、固定顺序、每条新进程/一次求解/自有进程树清理、配置和脚本身份、Node 与内存观察器身份，`failures=[]`。

**原始错误记录保留**

除文件共享中断外，以下原始失败均保留，解释与后续有效证据分别保存：

- H2 stable 同树检查错误要求动态查询量逐项完全相同，原失败不改写。
- Q1 第一版测试漏载 Tail，却要求 `strong` profile，实际 `strong-no-tail` 正确；修正期望后才有 final 门禁。
- OpenCV 近似图像处理在 initial-8 的 U1/U3 互换；真实浏览器像素正确，不修改人工参考迎合近似输出。GBK 诊断读取问题的原尝试与后续 UTF-8 诊断均保留。
- 历史单原型色距诊断把 initial-1 D9 红块判为橙，而均衡分类器正确；诊断失败不改写成“所有块最近原型都正确”。
- Tail [无准入握手的薄客户端尝试](benchmarks/next-speed-2026-10-02/q2-late-tail-unmanaged-loader-attempt.json) 复制了 managed-loader 参数却没有 resume/admission：5 条保存请求全部超时、未采用 strong/Tail、未运行 late Tail。依[无效方法说明](benchmarks/next-speed-2026-10-02/invalid-attempt-methodology.json) 排除出有效性能汇总，原数据不动；空 failures 数组不代表有效通过。
- 受控包浅状态 smoke 的 console 日志发生 GBK/UTF-8 解码差异，HTTP JSON 与断言正常；日志脚本改为 replacement 解码，没有为此重跑或挑选性能数据。
- 默认开关补丁初版漏导入 `os`，19 项合约失败的[原记录](benchmarks/next-speed-2026-10-02/default-python-contracts.xml)和[日志](benchmarks/next-speed-2026-10-02/default-python-contracts.log)保留；打包前修复，再获得 80 项通过的 final 记录。

**PGO 和算法扩展的边界**

两引擎已补 Portable PGO 构建/参数透传和独立训练脚本，训练集分别包含 8 组固定打乱，显式排除六验收状态的名称和冻结 Facelets，检查通过。Portable 使用 `-march=x86-64 -mtune=generic`，无 profile 时拒绝构建，普通 O3/LTO 仍是回退。HTM 原脚本声明训练集与实际固定 pgo16/known18 不一致的问题已消除。

本轮没有执行 PGO 训练、PGO 编译或 PGO AB，不能把支持脚本和排除检查称为 PGO 收益。P2 没有增加大 PDB/Tail、GPU、选择性逆状态剪枝或任务分发扩展；后续依据查询成本、worker 空闲和真实 Tail 命中提出独立假设。

QTM 训练脚本默认 `--expansion generic`，要求原生候选与实际 strong 查询均出现；可独立指定 `--expansion full-strong` 训练实验路径，此时另要求专用展开实际发生。两者不能混作同一训练身份。本轮决定先保留普通 Portable O3/LTO：完整请求在找到最短解的部分层有较大展开量差异，尚未确定退化原因，不把 PGO 与这一轮源码变体合并测量。

**正式 72 请求矩阵与采用判定**

冻结设计为六状态 × HTM/QTM × baseline/current × 三次，共 72 个请求，顺序 `initial-1、12、2、5、8、16`，各状态按 AB、BA、AB，两个引擎串行，每请求新建实际服务、普通默认 staged 启动、30 秒原入口 deadline，无已有 job/incumbent/证明缓存。新进程加暖 OS 文件缓存，不能称为冷磁盘测试。页面使用原上传/请求/轮询，识别单列；内存观察器每 0.5 秒查询 OS，不增加 HTTP 轮询。

严格成功以原 deadline 内后台确认最短为准，取入口相对终态时间；30 秒未确认记 PAR-2=60 秒。超时、取消、budget_exhausted 或中断层不能签最短证明。每状态三次全部保留，两版都超时则报告候选成本、合法下界和 gap；页面观察延迟、资源清理时间与 native search elapsed 不能替代严格完成时间。

| 正式项目 | HTM | QTM |
| --- | --- | --- |
| 有效记录数 / 预期 | 36 / 36 | 36 / 36 |
| baseline / current 严格成功数（各 18） | 9 / 10 | 18 / 18 |
| baseline / current PAR-2 均值 / 秒 | 34.605111 / 33.313333 | 11.380278 / 8.909611 |
| PAR-2 均值下降（目标 ≥15%） | 3.733%；未达标 | 21.710%；达标 |
| 双完成配对的逐状态中位数比之几何平均 | 1.422662 | 0.823141 |
| 同次配对新增超时 | 无 | 无 |
| 可重复 >5% 严格完成退化 | initial-12，+174.64% | initial-2，+47.49% |
| 页面首候选中位数 | 六状态下降 50.61%–62.31%，20% 目标通过 | 六状态约 1.77–1.79 秒，两版接近 |
| native 生命周期最大峰值 / 字节 | 345939968 / 345948160；+0.00237% | 3710513152 / 3710488576；−0.00066% |
| 峰值与逐状态内存中位数 ≤5% 增长 | 通过，同一 OS 观察口径 | 通过，同一 OS 观察口径 |
| 默认采用决定 | H1 关闭，H2 维持旧路径 | Q1 改回 generic，Q2 保持 legacy/off |

每个状态的严格时间仅使用同次新旧都完成的配对。`—` 表示没有这样的配对，不能拿单方完成或超时的页面时间补齐。

| 状态 | HTM baseline / current 中位数 / 秒 | HTM 相对变化 | QTM baseline / current 中位数 / 秒 | QTM 相对变化 |
| --- | ---: | ---: | ---: | ---: |
| initial-1 | — / — | baseline 三次超时，current 一次完成 | 17.891 / 18.266 | +2.10% |
| initial-12 | 5.843 / 16.047 | +174.64% | 9.922 / 6.953 | −29.92% |
| initial-2 | 5.469 / 5.625 | +2.85% | 4.110 / 6.062 | +47.49% |
| initial-5 | 12.906 / 13.156 | +1.94% | 15.250 / 11.297 | −25.92% |
| initial-8 | — / — | 新旧各三次超时 | 6.281 / 2.890 | −53.99% |
| initial-16 | — / — | 新旧各三次超时 | 8.781 / 7.594 | −13.52% |

HTM initial-12 三次 current/baseline 比为 `0.355561 / 2.770323 / 3.260260`，QTM initial-2 为 `1.706813 / 0.469221 / 1.497900`。两者均是三次配对中两次退化超过 5%，且中位数比超过 1.05。所有原始慢记录均保留，没有重测筛选。相应[退化事件摘录](benchmarks/next-speed-2026-10-02/regression-details.json)显示慢重复在找到最短解的部分层展开量更大；两版候选上界一致，QTM 两版在该层前均已采用完整 Tail。不能据此把原因定为 Tail 漏载，也不能将部分层展开差异当作完整同树吞吐比较；调度/上界到达与实际找到解位置的影响仍需独立调查。

[资源事件复核](benchmarks/next-speed-2026-10-02/formal-final/resource-event-audit.json)包含全部 72 请求。QTM 1,452 条原生额度帧的 loader_reserved + candidate + proof 均不超过 15，candidate 不超过 1；36 次均真实准入并采用 strong/Tail，新进程 `warm_reused=false`。baseline/current strong adopted 中位数为 1.774 / 1.766 秒，Tail adopted 为 2.133 / 2.078 秒。HTM 两版记录的初始证明额度均为 14，实验版候选活跃的页面快照中证明不超过 14；结束后最多 15。实际每请求均清理自有进程树，72 次照片参考差异和人工修正均为 0。

汇总独立回放 **10,641 条公式声明**，逐次检查重复公式的成本与 optimal 声明，`validation_errors=[]`；矩阵 `failures=[]`。这里的 10,641 是全部快照/事件中公式出现次数，包含重复，不是不同解的数量。

原汇总漏读 HTM 超时终态的 `progress.completed_depth`。追加汇总仅补齐已完成层、合法下界与 gap，另记录实际解析器 SHA 和原始输入 SHA；[增量审计](benchmarks/next-speed-2026-10-02/formal-final/bounds-analysis-audit.json)确认全部原主要指标、配对、采用门槛和其他记录字段完全一致，原 `summary.json` 不覆盖。[10 项解析器合约](benchmarks/next-speed-2026-10-02/summary-bounds-contracts.xml)通过，验证当前活动层不算已完成证明、缺失字段不推断、超时仍记 60 秒。

| HTM 超时状态 | 全部超时记录的最佳候选成本 | 已完成排除深度 | 合法下界 | gap |
| --- | ---: | ---: | ---: | ---: |
| initial-1（5 次） | 20 | 17 | 18 | 2 |
| initial-8（6 次） | 22 | 17 | 18 | 4 |
| initial-16（6 次） | 22 | 17 | 18 | 4 |

H1 的交付目标与严格确认分开判断，Q1 的单项收益也不免除完整请求退化门槛。六个固定状态只支持本回归集结论，不外推任意打乱的 p95 或普遍 30 秒成功率。

**保守默认包与最终功能证据**

最终包位于 `dist/next-speed-2026-10-03-defaults/RubicPhotoSolve`，[ZIP](../dist/next-speed-2026-10-03-defaults/RubicPhotoSolve-1.10.0-QtmStrong-windows-x64.zip) 含 153 文件、2,307,011,998 字节，SHA-256 为 `af0fba39fdbac43ee8b9c22d7ff57be1f433733a166afe84b33271efe7f446bc`。应用仍为 1.10.0 的本地工作候选，没有发布或覆盖原包。默认开关为 HTM early off、QTM generic、candidate legacy、late Tail off。

[最终源码冻结](benchmarks/next-speed-2026-10-02/current-defaults-identity.json)与[实际包身份核对](benchmarks/next-speed-2026-10-02/current-defaults-package-identity.json)分开保留。包内 HTM EXE SHA 为 `f85a87aca23957fdca40e5c677b366d8713dc943612dd6cdb4df891ba587338f`，QTM 为 `68b6e269893fec8ccd10f1d4d86fe4c126e1ab6797459e56ae271579bb9ab0ce`，主 EXE 为 `3bbb51135cec0bde492834a6b5e3fd961e0a08a97bd7dad924a6aa595730874d`。核对全部 42 个应用源码 SHA、两引擎全部构建源码 SHA、19 个包清单文件、5 个关键 Python 模块打包来源，原冻结 335 个文件重新核对无变化，17 个资产/缓存与原清单相同；两引擎仍为 Portable O3/LTO、非 PGO。实际[构建和完整归档检查日志](benchmarks/next-speed-2026-10-02/default-package-build.log)成功。

[最终 Python 合约](benchmarks/next-speed-2026-10-02/default-python-contracts-final.xml)为 80 项通过、0 fail/skip；新增默认策略合约验证首次内部候选不会发布或注入，上述预算结束后只交付最佳候选。实际包 QTM EXE 的[最终 oracle 门禁](benchmarks/next-speed-2026-10-02/default-native-oracle.xml)为 3 项通过、0 skip，覆盖全部 cutoff/接受坐标等价、默认 generic 与显式 full-strong 的独立浅层 oracle及 1/2/3 额度；新旧资源修复前后门禁的源码范围仍按前文区分。

[正常页面 8 次原始回归](benchmarks/next-speed-2026-10-02/default-functional/page.json)使用 initial-1 / 12 × HTM/QTM × baseline/保守默认 current × 一次，各条新进程，原 30 秒 deadline，照片与 Facelets 不变。这是功能/配置验收，未作为第二次性能采用矩阵，也未覆盖、替代正式三重复数据。[独立验证](benchmarks/next-speed-2026-10-02/default-functional/validation.json)回放 1,107 条公式声明无错误：两次 current HTM 均 early=false且只发布最佳候选；两次 current QTM 专用展开量为 0，仍真实采用完整 strong/Tail。页面无错误、照片差异/人工修正为 0，桌面和移动布局无溢出/遮挡；另人工查看 current QTM initial-12 两种截图正常。

这 8 条中 baseline 的 HTM initial-1 严格完成 18 步，current HTM initial-1 到 30 秒仍超时，合法候选 20、已证下界 18、gap=2；其余七条严格完成，其中 HTM initial-12 为 17、QTM initial-1 / 12 为 22 / 20。全部状态保留，未重新跑到成功。这份包提供保守默认、正确候选与资源修复的可审查交付，不宣布已通过六状态速度提升或无新超时的最终门槛。

1.10.1 发布整理时，将有效矩阵无损归档为 `formal-matrix.json.gz`，避免超过 GitHub 单文件限制。解压后的 351,749,493 字节及 SHA-256 与原文件完全相同；[归档身份](benchmarks/next-speed-2026-10-02/formal-final/formal-matrix-archive.json)记录两个文件的散列。当前解析脚本直接支持 `.gz`，复现全部记录、主要指标、错误和采用决定均与原汇总一致。本报告中的 1.10.0 实验包身份和历史计时不变，不作为 1.10.1 的速度成绩。

复现已有记录解析与身份检查可运行以下命令；重新运行求解会产生新的实验记录，不能覆盖本轮原始文件。

```powershell
.venv\Scripts\python.exe tests/summarize_next_speed.py docs/benchmarks/next-speed-2026-10-02/formal-final/formal-matrix.json.gz --output .codex/next-speed/summary-repro.json
.venv\Scripts\python.exe tests/verify_next_speed_defaults.py --input docs/benchmarks/next-speed-2026-10-02/default-functional/page.json --output .codex/next-speed/default-validation-repro.json
.venv\Scripts\python.exe tests/verify_next_speed_package_identity.py --package dist/next-speed-2026-10-03-defaults/RubicPhotoSolve --baseline docs/benchmarks/next-speed-2026-10-02/baseline-identity.json --current docs/benchmarks/next-speed-2026-10-02/current-defaults-identity.json --output .codex/next-speed/default-package-identity-repro.json
```
