**正式矩阵的验收脚本与只读观察**

正式矩阵使用 `tests/verify_next_speed_page.cjs`，每个请求启动独立实际包，按冻结的 AB、BA、AB 顺序串行运行六状态、两种度量、两个版本、三次重复，共 72 次。原照片识别结果、参考差异和高级 Facelets 输入覆盖单独记录；求解固定使用同一份冻结 Facelets。请求超时仍为入口起算的 30 秒，正常页面自身的一秒轮询保持原样。

原始报告包含 `harnessSourceSha256`，记录页面矩阵脚本、Windows 内存观察器、原子报告写入器和汇总脚本的源码身份；同时记录 Node 可执行文件、版本、观察器 Python 路径、配置 SHA 和实际包内 EXE 身份。这些小源码散列在首个请求之前采集，不在求解计时期间重算。

报告保存由 `tests/next_speed_atomic_report.cjs` 负责。先写同目录的完整临时 JSON，再异步原子替换报告；临时 Windows 共享锁使用 25 毫秒间隔重试，最多 5 秒。重试不阻断页面轮询，也不修改已经采集的响应 `seconds`。持久化错误与页面错误分开；每个请求结束和整个矩阵结束均强制 `flush`。最终无法替换时脚本失败，完整 `.uncommitted.json` 文件保留供恢复，不能把旧报告当作最终成功报告。

完整报告只在每轮 native launcher 启动前、该轮自有进程树清理后、以及最终结束时序列化并保存。搜索期间仅在内存追加全部原始响应事件，响应监听器不调用完整报告保存；随着 72 次历史数据变大，也不会在活跃求解时每秒序列化历史数据来阻塞页面观察。进度查看控制台的 `case_start` 和每轮结果行，完整记录在该轮结束后通过共享字节快照读取。若外部硬杀发生在当前轮期间，当前轮未持久化的事件可能丢失，必须按中断失败记录保留，不能补造响应或宣称该轮成功。

正式计时期间不要用普通 `Get-Content` 打开正在更新的 JSON。它可能建立不允许替换/写入的共享句柄。需要读取时，先通过允许读、写、删除共享的句柄复制字节快照，关闭句柄后再解析：

```powershell
$reviewPath = [IO.Path]::GetFullPath('docs/benchmarks/next-speed-2026-10-02/formal-final/formal-matrix.json')
$reviewShare = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
$reviewStream = [IO.File]::Open($reviewPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, $reviewShare)
$reviewReader = [IO.StreamReader]::new($reviewStream, [Text.Encoding]::UTF8)
try {
    $reviewSnapshot = $reviewReader.ReadToEnd()
} finally {
    $reviewReader.Dispose()
}
$reviewData = $reviewSnapshot | ConvertFrom-Json
$reviewData.cases | Select-Object name, metric, label, repeat, pageWallSeconds, processTreeStopped
```

原子替换下，该句柄读取某一个完整版本的报告，不会锁住下一个版本的替换。不要高频解析不断增长的全矩阵 JSON；只审查必要的已完成记录，或读取已完成日志。正式计时期间不同时运行引擎、构建、测试或完整资产散列。

`tests/observe_next_speed_memory.py` 每 0.5 秒通过 Windows OS 查询本轮 launcher 后代进程，不发送 HTTP。报告分别提供 native 单进程生命周期 `PeakWorkingSetSize` 和整个已观察进程树的同时工作集之和，两者不是相同口径。结束前再采一次原生常驻进程峰值，然后才终止本轮 launcher 树。

文件共享导致的首次中断及一次复测决定保留在 `docs/benchmarks/next-speed-2026-10-02/file-sharing-attempt-methodology.json`，中断尝试的两个 HTM 超时、原始响应和失败仍保留，不因快慢删除。冻结后的正式记录由 `tests/summarize_next_speed.py` 重放每次公式声明、核对已知最优成本，并只使用后台入口相对终态时间。缺少严格终态时间时不可用原生 elapsed、资源占用时间或页面时间替代；超时惩罚始终为 60 秒。

有效正式矩阵已完成，原始报告位于 `formal-final/formal-matrix.json`，原汇总 `formal-final/summary.json` 保留不动。后续 `summary-with-bounds.json` 补读 HTM timeout 的 `progress.completed_depth`，优先使用终态/结果/进度中的完整层和报告的合法下界，绝不以 `current_depth` 推断排除证明；缺失证据保持 null。它另记当前解析器 SHA 与原始输入 SHA，不能把矩阵采集时保存的旧解析器 SHA 改成新版本。增量审计确认 PAR-2、配对比值、内存与采用门槛均不变，10 项合约验证超时仍取60秒、活动层不算完成、未知下界不补造。

保守默认包的 `default-functional/page.json` 是单次两状态、两引擎、新旧两包共8条功能记录，`formalMatrix=false`；`tests/verify_next_speed_defaults.py`独立验证全部公式、关闭的实验开关及布局。它的HTM initial-1 current超时保留，不按新性能矩阵计分，也不替换72次实验数据。PGO/性能采用仍以各自冻结方案和完整数据为准。
