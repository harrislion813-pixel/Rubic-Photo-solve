# HTM / QTM 实施交付记录

日期：2026-09-28。对应 `docs/ai-htm-qtm-implementation-guide.md` 阶段 A–G。

## 行为与实现

- 二阶和三阶的 UI、HTTP、Python 及 C++ 求解入口支持 HTM / QTM，缺省 HTM。`R` 和 `R'` 两模式均为 1；`R2` 分别为 1 / 2；`depth` 表示总代价。
- 默认完整预算：二阶 HTM 11 / QTM 14，三阶 HTM 20 / QTM 26。显式预算为整数，HTM 接受 0–20，QTM 接受 0–26；二阶按本模式直径截断。零预算和较小预算不会被解释成状态非法。
- 三阶保持完整严格搜索，全部 18 种动作按请求固定模式加权。HTM PDB 保留原文件语义，只作 QTM 合规下界；QTM 不查询已加载的 HTM Tail，且不走其返回或失败剪枝。
- 快速两阶段候选仍由 HTM 生成器产生，服务按目标模式重新计价并标记未证明。候选更新按总代价比较；全层排除或有效下界证明完成后才 `optimal=true`。
- `complete` 仅表示最短性已证明；预算不足为 `budget_exhausted`，超时和取消不提升证明。无候选时 `depth=null`，不会显示“已有可执行解”。
- 二阶延续整体旋转也算复原的定义。HTM 全 9 动作 BFS，QTM 六种正反 90° 动作 BFS，允许连续同面；恢复公式可包含半转，并按每个动作代价减少剩余距离。
- 两张二阶表各覆盖 3,674,160 个规范状态，直径 11 / 14；缓存模式 magic + SHA256 校验，原子写入，损坏重建、只读回退、初始化和锁等待均检查 deadline。
- UI 在求解开始时固定请求快照（阶数、facelets、模式、预算、超时），切换模式取消旧任务、清除结果与轮询，保留照片和人工校正。迟到 POST / GET 不覆盖新请求，切换本身不启动搜索。
- Windows 脚本预生成并校验双表，核查原生双模式能力，将双表纳入必需资产及复制列表。首次功能交付仅执行预检；后续 v1.5.0 发布验收见本文末尾。

## 接口与缓存

`cube_app/metrics.py` 集中提供 `normalize_metric`、`move_cost`、`solution_cost`、`default_max_depth`、`resolve_max_depth`。位置参数保留原含义，新增模式参数在末尾或作为关键字；共享 solver 不保存可变全局模式。

HTTP 新增 `metric` 字段（仅 HTM / QTM，大小写可统一）；结果、任务、进度及取消快照携带实际模式。活动任务 key 为 `(facelets, cube_size, 实际max_depth, metric, proof_version=2)`。

原生 ready 声明 `protocol_version=3`、`proof_version=2`、`metrics=["HTM","QTM"]`。新请求 8 字段使用真实 TAB：

```text
solve <request_id> <facelets> <max_depth> <remaining_seconds> <threads> <metric> <incumbent_moves>
```

保留旧 7 字段与 5 字段请求，并明确按 HTM 解释；旧 5 字段不复用证明缓存。基准使用 `serve --no-proof-cache`，新协议仍独立完成每次证明。原生缓存 key 包含状态、模式和 proof2，只保存完全排除的预算层。旧 EXE 能力不匹配、返回模式/总代价不匹配、动作非法或无法复原均视为引擎错误；Python 回退继续使用原始 deadline。原生超时不会重启 Python 搜索。

## 主要文件

| 范围 | 文件 |
| --- | --- |
| 统一计价与 Python 严格搜索 | `cube_app/metrics.py`, `cube_app/optimal.py` |
| 原生搜索、协议和返回验证 | `native/include/solver.hpp`, `native/src/solver.cpp`, `native/src/main.cpp`, `cube_app/native.py` |
| 二阶双表与最短公式恢复 | `cube_app/two_by_two.py`, `cube_app/two_by_two_tables.py` |
| HTTP、任务生命周期和候选 | `server.py` |
| 前端模式选择与异步结果 | `web/index.html`, `web/app.js`, `web/solver-client.js`, `web/styles.css` |
| 验收与基准 | `tests/test_metrics.py`, `tests/test_metric_search.py`, `tests/test_metric_api.py`, `tests/test_native_solver.py`, `tests/test_two_by_two.py`, `tests/solver_ui.test.js`, `tests/benchmark_native.py`, `tests/benchmark_metric_cache.py`, `tests/check.ps1` |
| 使用、发布和实施记录 | `README.md`, `release/README-Windows.txt`, `release/build_windows.ps1`, `CHANGELOG.md`, 本记录及实施指南 |

## 独立最短性证据

三阶 HTM oracle 使用全部 18 动作单位 BFS；QTM oracle 使用 12 种正反 90° 动作单位 BFS，允许连续同面。生产搜索与独立浅层准确距离一致，且 canonical 同面合并/对面交换剪枝的浅层完整距离图一致。Python 串行、真实多进程和 C++ 单/多线程、正/逆方向均实际复原并核对代价。原生测试覆盖无 PDB、部分 PDB 和完整 PDB 的 QTM 下界有效性。

固定二阶反例：`LLURUFDDRBDRLFDBBFLFUURB`。独立角块 meet-in-the-middle BFS 证明 HTM 最短 7、QTM 最短 8；合法 HTM 最短公式 `F2 U' R2 U' F R U2` 按 QTM 计 10。QTM 求解输出代价 8，说明实际重新优化了目标，未将旧公式仅重计价。

## 性能记录

基线源码提交 `ae73ca81af1ed077c059f3345377190bf0ce2882`。修改前 27 项指定 Python 回归和原求解 UI 测试通过。原有 `.pytest_cache` 写权限警告在后续使用可写缓存时消失，未删除原目录。

数据：`benchmarks/htm-before.json`、`benchmarks/htm-after.json`、`benchmarks/qtm-after.json`。同样本、4 线程、每样本搜索限时 2 秒、staged、1 次重复，证明缓存关闭。报告记录 EXE/PDB SHA256、编译源码哈希、公式、加权候选、完成预算、节点、冷启动与内存；超时样本保留。

| 模式 / 样本 | 修改前 wall 秒 | 修改后 wall 秒 | 结论 | 修改后节点 / 完成排除预算 |
| --- | ---: | ---: | --- | --- |
| HTM repo14 | 0.005324 | 0.005642 | 最短 14 | 9,078 / 13 |
| HTM pgo16 | 0.426390 | 0.190025 | 最短 16 | 759,260 / 15 |
| QTM repo14 | — | 0.400702 | 最短 17 | 1,663,393 / 16 |
| QTM pgo16 | — | 2.000750 | 超时，候选代价 21，尚未证明 | 8,517,759 / 16 |

原生冷启动 HTM 修改前 0.7074 秒、修改后 0.7443 秒，QTM 0.7180 秒；记录的进程峰值工作集约 328 MiB。HTM 启用已加载的 Tail；QTM 同样加载资产但 `tail_enabled=false`、Tail 查询为 0。这里只各测 1 次，未据此宣称稳定加速比。打乱长度没有作为最短长度依据。

另测同进程 HTM → QTM → HTM → QTM 重试，数据 `benchmarks/cache-retries.json`：初次 QTM 约 0.4250 秒、1,663,303 节点；完整排除预算已缓存后的同模式重试约 0.00027 秒、0 新节点。HTM 首次含进程启动，不能直接与热重试相比。该试验不混入独立证明基准。

QTM 首版使用较弱的 HTM 下界，复杂三阶状态可能超时；26 是完整搜索的预算上限，不能保证所有状态在默认超时内完成证明。未生成新的 QTM 三阶大型 PDB / Tail。

## 可复制命令

```powershell
.\.venv\Scripts\python.exe -m cube_app.two_by_two_tables --metric HTM
.\.venv\Scripts\python.exe -m cube_app.two_by_two_tables --metric QTM
.\native\build.ps1
.\tests\check.ps1
.\.venv\Scripts\python.exe -m pytest -ra -m "native_binary or native_pdb" -o cache_dir=.cache/pytest-cache
.\release\build_windows.ps1 -PreflightOnly
.\.venv\Scripts\python.exe tests/benchmark_native.py --metric HTM --cases repo14,pgo16 --threads 4 --timeout 2 --repeats 1 --variants staged --output docs/benchmarks/htm-after.json
.\.venv\Scripts\python.exe tests/benchmark_native.py --metric QTM --cases repo14,pgo16 --threads 4 --timeout 2 --repeats 1 --variants staged --output docs/benchmarks/qtm-after.json
.\.venv\Scripts\python.exe tests/benchmark_metric_cache.py
git diff --check
```

以下为真实合法 `R2` 状态，可分别验证 HTM 1 / QTM 2：

```powershell
$facelets = & .\.venv\Scripts\python.exe -c "from cube_app.cubie import CubieCube,MOVE_INDEX,to_facelets; print(to_facelets(CubieCube().apply_move_index(MOVE_INDEX['R2'])))"
.\native\build\cube_solver.exe solve $facelets --metric HTM --threads 4 --timeout 5
.\native\build\cube_solver.exe solve $facelets --metric QTM --threads 4 --timeout 5
```

## 最终验收

- `tests/check.ps1`：exit0；4 个 Node 测试入口逐一通过，Ruff 通过，Python **146 passed / 73.30 秒、无跳过**，compileall 通过。运行时使用 `PYTEST_ADDOPTS=-o cache_dir=.cache/pytest-cache`、`REQUIRE_NATIVE_BINARY=1`、`REQUIRE_NATIVE_PDB=1`。
- Python计价/严格搜索专项 54 passed；API专项 27 passed；二阶最终 11 passed；原生模块共25项已在完整检查实际运行（包括最后新增的QTM取消/缓存隔离）。完整检查已覆盖native标记，未重复执行同一标记子集。
- `native/build.ps1`：编译成功，g++ 16.1.0；Python 3.12.14、pytest 8.4.2。首次功能验收 EXE SHA256 `0823726B72C8975A89CD208D1DAAAA0D2DB25CC6FEB1587F7629C73C75D4F67C`，after / cache 性能报告一致。
- 二阶双模式 CLI：均完成覆盖与直径校验。
- `release/build_windows.ps1 -PreflightOnly`：exit0，双表与真实EXE协议能力检查通过。
- `git diff --check`：通过。
- 没有因编译器、PDB或依赖缺失而未验证的要求。首次功能交付未构建便携 ZIP；后续发布见下节，仍未生成后续优化范围的QTM专用三阶大型表。

实际浏览器检查：390 × 844 视口切换 QTM，布局无横向溢出，显示“算两步（QTM）”和 `R2` 计 2 步，切换后等待点击开始。截图：`benchmarks/qtm-mobile.png`。

首次功能交付时保留原有 `.codex/` 与指南，未提交或发布；后续用户授权发布 v1.5.0。

## v1.5.0 发布验收

- 唯一版本源与本地包元数据更新到1.5.0；CHANGELOG转为1.5.0，仓库入口及应用README同步。
- 补齐C++ clang-format CI门禁并重新编译；发布EXE SHA256 `2CF746712DD31D3347C4F2B5868A82D3CA43F0FC284ED73A275C9457C795FFE3`。前文性能JSON保留首次功能验收时的EXE/source哈希，属于历史基准，未冒充本次发布重测。
- 版本修改后完整check再次146 passed/73.30秒，无跳过；4个Node入口、Ruff、compileall和C++格式检查通过。CI同规则覆盖率测试119 passed、27 deselected，75.45%高于70%门禁。
- 本地构建 `release/build_windows.ps1 -IncludeTailPdb` 成功，ZIP 221,708,620字节；SHA256 `F6145734924F7AB5943E3105F6301CD5F123DD5DAB709A4E31CA87015A921F2B`。冻结应用实际启动验证/api/version及页面1.5.0，二阶/三阶HTM/QTM四条R2复原均返回严格最短1/2步。ZIP CRC和双表资产检查通过。机器可读证据 `release-v1.5.0.json`。
- GitHub标签发布仍由完整远程CI门禁生成正式可下载ZIP；远程包不包含可选Tail，可能与上述本地IncludeTailPdb包大小和哈希不同。
- 个人 `.codex/` 目录保留并忽略，不纳入版本；当前任务代码、指南、交付和基准记录全部纳入发布提交。
