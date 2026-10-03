**Controlled baseline · P0 观测与统一资源配额**

原冻结基线位于 `.codex/next-speed/baseline`，继续保持源码和 EXE 原样。正式请求的受控对照位于独立副本 `.codex/next-speed/baseline-observed`。该副本只加入 P0 事件/计时/内存观测和统一资源配额，不引入 H1 的提前候选交付、取消算法改造或启动时 incumbent 刷新，也不引入 H2、Q1、Q2、PGO 的搜索改动。

候选仍按冻结算法先搜索、再用原最多 1.5 秒预算继续改进，结束后才更新 job/incumbent 并返回原 HTTP 分支。观察回调记录首次候选和后续改进，但不发布。快速证明仍优先返回，两个 native 快速完成分支都包含 `job_id`，便于页面用原轮询取得清理后的诊断。

HTM 的 `terminal_seconds` 从原 `/api/solve` 入口的 monotonic 时间计算，在合法原生结果或 Python 结果确认终态时冻结，候选搜索、锁释放和 HTTP/轮询延迟不会延后它。QTM 在客户端收到 native result 时记录 `client_terminal_at`，透传验证结果并冻结请求相对终态；`strict_confirmed_seconds` 仅在验证成功且 `optimal=true` 时赋值。超时、取消、error、budget_exhausted 的时间可记录，但不构成严格完成。

两个版本 HTM 使用相同的 Windows `GetProcessMemoryInfo` helper，在 native ready、result、finish、stop 边界记录进程 ID 和生命周期工作集峰值，job 保存已见最大值。范围标为 `native_process_lifetime_peak`，不能解释成 Python 服务与浏览器之和。QTM 保留冻结版已有的 memory diagnostics，不改变内存准入或 loader 逻辑。缺少操作系统测量时保留 `null`，不填造零峰值。

资源规则：15 个总额度在候选结束前分配为 14 proof + 1 candidate，候选未启动时也保留 1 额度；预算结束后允许下一个完整层边界恢复 15 proof。1 线程串行候选再证明，沿用原绝对 deadline。候选只能使用本 job 的 proof lease，proof lock 会等已启动的同步候选退出再放行下个 job；无 deadline 的 queued 请求被取消也能结束 lease 等待。Python fallback 的 worker 上限遵循相同配额，并在调用结束后恢复原 solver 设置。

受控源码差异共 8 个文件：`server.py`、HTM `fast.py/native.py`、QTM `backend.py/native.py`、HTM `solver.hpp/main.cpp/solver.cpp`。新增的 `tests/test_controlled_baseline.py` 仅包含 mock 和 AST 门禁。独立 patch 使用普通 `a/...` / `b/...` 路径，可在冻结源码副本上检查和应用；资产与 cache 通过目录 junction 使用原冻结身份的共享输入。

验证命令从 observed 副本目录执行：

```powershell
& ../../../.venv/Scripts/python.exe -m pytest tests/test_controlled_baseline.py -q --junitxml=../../../docs/benchmarks/next-speed-2026-10-02/controlled-baseline-contracts.xml
```

21 项通过，耗时 0.50 秒，没有调用真实求解器。门禁覆盖：移除观测脚手架后 Python 候选搜索和 QTM native bridge AST 与冻结版完全一致；first/improvement 回调不提前返回；1/2/3/15 额度、同步 HTTP、快速证明入口计时；终态早于候选和资源清理；queued lease 等待和无 deadline 取消；Python fallback；dynamic capability 与旧 EXE 回退；冻结版 incumbent 发送顺序；H1/对照 memory helper AST 一致及峰值 max；Windows 当前进程真实内存 API 烟测；QTM 客户端终态透传、events 和清理后的时间冻结。

源码身份复核与 patch 见 `controlled-baseline-identity.json`、`controlled-baseline.patch`，pytest 原始结果见 `controlled-baseline-contracts.xml`。首次身份复核重算原冻结副本 335 个已复制文件，零差异；大资产采用原冻结 manifest，不在轻量审计中重新散列。

2026-10-03 已完成实际 `QtmStrong` 包构建，使用根 `.venv/Scripts/python.exe` 以及 `-SkipNativeBuild -SkipTableBuild`。受控 HTM 复用现有同源 Portable O3/LTO 非 PGO 构建：逐一核对 12 个 C++ 源码的 SHA 与 build-info 全部一致，无需重新编译。受控包 HTM EXE 的 SHA-256 为 `f85a87aca23957fdca40e5c677b366d8713dc943612dd6cdb4df891ba587338f`；QTM EXE 继续使用原冻结 `8c2912c43e267ea32ac9daea77902bc2258d91ef35f6a456e92c165734d5376a`。原 `.codex/next-speed/baseline` 源码、EXE、报告均未修改。

包目录为 `dist/next-speed-controlled-baseline/RubicPhotoSolve`，ZIP64 包包含 153 个文件、2,306,988,398 字节。原始构建日志为 `baseline-package-build.log`，包与 native 身份、5 个关键 Python 模块的 PyInstaller 来源及实际 API 结果为 `controlled-baseline-package-identity.json`。所有关键 Python 模块均来自 observed 副本，两个 native build-info 和实际 EXE 散列均匹配该副本。

实际包分别用新进程执行一个 R 动作的浅状态正常请求：HTM、QTM 都严格完成，成本 1，独立 cubie 重放正确，进程树均已清理。HTM 返回 `job_id`、入口相对 `terminal_seconds`、完整 `timing_events`、15 总额度/14 初始证明额度、`dynamic_threads=true`、真实 native PID 和工作集峰值；QTM 返回 `client_terminal_at`、`terminal_seconds`、`strict_confirmed_seconds` 和原始 events。此次浅状态验证不代表六组性能或实际深层 14→15 的恢复收益。

实际包核验/烟测脚本为 `.codex/next-speed/check_controlled_package.py`，从仓库根目录复现：

```powershell
& .venv/Scripts/python.exe .codex/next-speed/check_controlled_package.py
```

该脚本检查 module 来源、Portable/non-PGO 参数、全部 native 源码身份和包 EXE，并顺序启动两个浅状态请求。原始烟测的 console 日志读取遇到 GBK/UTF-8 解码差异，HTTP 断言与 API 原始 JSON 均正常；脚本已改为 replacement 解码，但没有为此重跑烟测。正式矩阵可以使用此包。本报告不提供性能改善结论，默认页面计时和工作集门槛由后续正式矩阵判定。
