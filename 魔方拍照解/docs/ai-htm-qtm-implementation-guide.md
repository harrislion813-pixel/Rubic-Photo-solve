# HTM / QTM 可选最短解：AI 实施指南

编写日期：2026-09-28。本文原为依据当日代码检查编写的实施任务说明；阶段 A–G 现已执行，完成记录见第 11 节与 `docs/htm-qtm-delivery.md`。

## 1. 任务目标与交付范围

为“魔方拍照解”增加计步方式选项，同时支持二阶和三阶：

| 模式 | 顺时针 90° | 逆时针 90° | 180° | 默认 |
| --- | ---: | ---: | ---: | --- |
| HTM | 1 | 1 | 1 | 是，保持原有行为 |
| QTM | 1 | 1 | 2 | 否，用户可选择 |

输出必须是所选计步方式下的严格最短解，或明确标识为“尚未证明最短”的可执行候选解。超时、取消、搜索预算不足均不得冒充最短性证明。

完成范围：统一计价、Python 严格搜索、C++ 严格搜索、二阶准确距离表、HTTP 与原生协议、任务及证明缓存、前端选项、测试、文档、Windows 打包资产适配。

首次交付复用经过验证的 HTM 剪枝下界，QTM 搜索禁用现有 HTM Tail 终局捷径。QTM 专用三阶大型 PDB 和 Tail 表属于有基准依据后再做的优化，不是首次交付的前置条件。

本指南本身不要求重写照片识别、颜色分类或魔方状态表示，也不要求提交、推送、打标签或发布版本。实际执行范围以用户当时授权为准。

## 2. 接手方式与现有代码地图

应用根目录为包含 `server.py`、`cube_app/`、`native/`、`web/` 的目录。编写时路径：

`C:/Users/harriron/Desktop/Rubic-Photo-solve/魔方拍照解`

下文路径相对此应用根目录。执行前读取适用的 `AGENTS.md`，检查 `git status --short`，保留用户已有修改。按函数名重新定位代码，不依赖本指南编写时的行号。

开始修改前，先记录当前 HTM 相关测试结果及一组可重复的性能基线，注明源码/EXE/表文件版本、线程数和超时。保留基线数据供阶段 G 对照；已有失败与本次新增问题分开报告。随后按 A→G 实施，并在每阶段完成后更新本文件的复选框及交付记录。

| 文件 | 现状 / 修改重点 |
| --- | --- |
| `cube_app/cubie.py` | 18 种动作按每面 `"" / "2" / "'"` 排列；确认 Python/C++ 动作顺序一致 |
| 新增 `cube_app/metrics.py` | 统一计步规则、公式代价、模式校验与默认搜索上限 |
| `cube_app/optimal.py` | `OptimalSolver`、串行/多进程根分支、Phase 1/2 递归、候选上界和证明进度均假定单位代价 |
| `cube_app/fast.py` | 快速两阶段候选生成；目前返回 HTM，不能直接将该结果标成 QTM 最短 |
| `cube_app/tables.py` | 坐标转移表和 HTM 剪枝表；首版保留其原有度量语义 |
| `cube_app/two_by_two.py` | DBL 角块规范化、准确距离查询、映射回用户面向、复原验证 |
| `cube_app/two_by_two_tables.py` | 9 种 U/R/F 动作的 HTM BFS；磁盘缓存及内存缓存需按模式区分 |
| `native/include/solver.hpp` | `SolverOptions`、结果和进度结构；增加度量信息和统一代价辅助函数 |
| `native/src/solver.cpp` | DFS、`split_task`、逐层搜索、候选更新、终局捷径、已完成证明深度 |
| `native/src/main.cpp` | CLI、常驻协议、JSON 输出、候选控制消息及进程内证明缓存 |
| `native/src/tail.cpp`、`native/include/tail.hpp` | 现有表为 HTM 准确后缀；QTM 首版不使用该捷径 |
| `native/src/pdb.cpp`、`native/include/pdb.hpp` | HTM PDB 元数据和距离语义；不得仅改标签后当作 QTM 准确距离 |
| `cube_app/native.py` | 协议握手、请求传输、候选更新、原生返回值复原与计价验证 |
| `server.py` | 请求参数、快速候选、后台任务、任务去重、回退与统一 deadline |
| `web/index.html`、`web/app.js`、`web/solver-client.js`、`web/styles.css` | 模式选择、请求快照、结果标记、进度、切换取消及样式 |
| `tests/` | Python、C++、API、生命周期、前端和基准验证 |
| `release/build_windows.ps1`、`README.md`、`release/README-Windows.txt` | 双模式二阶表预生成、校验、复制及使用说明 |

现状排查入口：

```powershell
git status --short
rg -n 'HTM|QTM|metric|incumbent|completed_depth|protocol_version|proof_version' cube_app native server.py web tests release
rg -n 'depth_left - 1|depth - 1|len\(moves\)|len\(incumbent\)|incumbent\.size|moves\.size|max_depth' cube_app native server.py web
```

这些搜索用于逐项审计，不能全局替换所有 `len`、`size` 或 `depth - 1`。容器长度、循环次数、统计和调度阈值仍可能表示动作项数；`C - 1` 也仍是排除所有更低整数代价的正确界限。

## 3. 必须保持的正确性约束

1. 搜索目标是 `sum(move_cost(move, metric))`。QTM 下不能用 `len(moves)` 或 `moves.size()` 代替总代价。
2. 已有公式重新计价只得到一个可行上界，不构成 QTM 最短性证明。
3. 每次求解的 `metric` 是固定请求参数。不要修改共享 solver 的可变全局模式来切换请求。
4. 同一请求的最大预算、候选上界、下界、剩余预算、证明进度和返回步数必须使用相同单位。
5. `optimal=true` 必须同时满足：动作可以复原输入状态；动作总代价为 C；所有代价小于 C 的解已被搜索或有效下界严格排除。
6. 对正在搜索但未完成的预算层，不能写入“已完成证明”缓存。取消、超时和进程故障不能提升证明结论。
7. 搜索仍保留 18 种动作，包括 `R2` 等。若只保留 12 种 90° 动作，却沿用“禁止连续同面”的剪枝，会丢失 `R R` 这类必要路径。首次实现采用保留 18 动作并加权的方案。
8. 现有同面合并、对面交换去重仅在不增加所选代价的前提下保留，并由独立穷举测试验证。
9. `R'` 代表逆时针 90°，QTM 代价为 1；不能按顺时针 270° 计为 3。
10. 二阶继续沿用现有“整体转动后的已复原姿态也算复原”定义；三阶继续使用现有固定颜色/面向定义。

### 剪枝表复用依据

对任意三阶状态 s：

```text
h_HTM(s) <= d_HTM(s) <= d_QTM(s)
```

因此已经证明有效的 HTM 全局搜索下界仍可用于 QTM 剪枝，只是可能较弱。Phase 2 的受限动作剪枝表仍只在对应受限子搜索中使用。

坐标转移表描述物理状态变化，与计步方式无关，可以共享。已有 HTM 表的文件名、表头和内容语义保持 HTM；“在 QTM 中用作下界”不等于“该表已变为 QTM 表”。

Tail 表不同：现有实现命中后直接拼接 HTM 最短后缀，不能保证该后缀在 QTM 下最短或不超过剩余预算。QTM 首版必须绕过整条 Tail 专用分支，包括基于该表的直接返回及失败剪枝，而不是只重算返回值。

## 4. 对外接口与计价约定

### 4.1 Python 与 HTTP

建议公共辅助接口：

```python
normalize_metric(value) -> str
move_cost(move, metric) -> int
solution_cost(moves, metric) -> int
default_max_depth(cube_size, metric) -> int
```

函数签名为建议；实现应保持职责集中。Python 模块和 C++ 各自使用统一辅助函数/代价数组，避免在多个调用点散落 `endswith("2")` 判断。

- 缺省 `metric` 为 `HTM`；明确传入的模式只接受 HTM/QTM，可统一大小写，其他值返回参数错误。
- 向现有函数增加参数时保留已有位置参数含义，优先在现有参数之后增加 `metric="HTM"` 或使用仅关键字参数。
- 求解入口在未提供 `max_depth` 时按魔方阶数和模式确定默认值，不能因函数签名仍写死 20/11 而截断 QTM。
- 建议用 `max_depth=None` 表示未指定，进入函数后再解析默认值。

| 魔方 | HTM 完整搜索上限 / 默认值 | QTM 完整搜索上限 / 默认值 |
| --- | ---: | ---: |
| 二阶 | 11 | 14 |
| 三阶 | 20 | 26 |

上述是覆盖全部合法状态的搜索上限，不是完成搜索的耗时保证。显式较小预算必须被尊重；不足时不能误报状态非法或声称候选已最短。

保持现有 HTM API 的有效输入兼容：当前二阶接受通用 `max_depth` 后会按二阶直径截断。可继续按所选模式采用通用输入范围 HTM 0–20、QTM 0–26，再将二阶实际预算截到 11/14；不能把 QTM 也截到旧的 11/20。对非整数和超出支持范围的输入给出明确错误。

新增请求字段：

```json
{
  "facelets": "<合法的 facelets 字符串>",
  "cube_size": 3,
  "metric": "QTM",
  "max_depth": 26,
  "timeout_seconds": 180
}
```

返回与任务字段约定：

| 字段 | 约定 |
| --- | --- |
| `metric` | 返回实际搜索使用的 HTM/QTM，包括零步、等待、超时等分支 |
| `moves`、`solution` | 保留标准公式记法，允许包含 `R2` |
| `depth` | 动作总代价；尚无可用解时保留现有 null 语义 |
| `incumbent_depth` | 当前候选在该模式下的总代价 |
| `lower_bound`、`upper_bound`、`current_depth`、`completed_depth` | 均按该模式计价；保留原字段名以减小兼容影响 |
| `optimal` | 最短性已严格证明才为 true |
| `proof_status` | 保留任务状态体系；只有证明完成才能为 complete |

任务详情、进度和最终结果均带模式信息，避免前端依赖当前选择框推断旧任务的单位。无需为了此功能新增“公式项数”字段；若以后展示该值，应另起字段，不能覆盖 `depth`。

### 4.2 C++ 协议

将常驻协议升级为明确支持双模式的版本，建议 `protocol_version=3`、`proof_version=2`，ready 消息声明 `metrics=["HTM","QTM"]`。

建议新求解帧按以下顺序传输，字段间为真实 tab，结尾为换行：

```text
solve <request_id> <facelets> <max_depth> <remaining_seconds> <threads> <metric> <incumbent_moves>
```

同步修改发送、解析、测试和基准客户端；确保空候选字段仍能正确解析。`cancel`、`incumbent` 控制帧沿用 request ID，候选按照该活动请求的模式计价。

CLI 增加 `--metric HTM|QTM`，未指定模式默认 HTM；指定 QTM 且省略 `--max-depth` 时使用 26。

旧 EXE 不支持该协议时明确报告能力不匹配，并按现有机制使用剩余 deadline 回退到支持对应模式的 Python 搜索。不得将 QTM 请求交给 HTM 引擎后仅改结果标签。

如果继续支持现有七字段求解帧或五字段基准帧，将其明确解释为 HTM；旧五字段基准帧仍应关闭证明缓存复用。不要让协议升级悄悄破坏基准的独立重复测量。

## 5. 按顺序执行的实施阶段

### 阶段 A：计价基础与最小回归

- [x] 增加模式校验、动作代价、公式总代价及默认搜索上限。
- [x] C++ 增加相同语义的枚举/辅助函数，逐一核对全部 18 种动作。
- [x] 固定例子：空公式为 0；`R` 和 `R'` 在两种模式下为 1；`R2` 为 1/2；`R2 U' F2` 为 3/5。
- [x] 覆盖无效模式、无效动作，以及动作序列逆转前后总代价相同。

完成条件：两种语言的计价一致，默认 HTM 调用兼容。

### 阶段 B：Python 三阶严格搜索

- [x] 将 metric 传入公共入口、Phase 1、Phase 2、根分支、多进程任务和工作进程。
- [x] 对每个候选动作单独计算 `next_remaining = remaining - cost(move)`，小于 0 时跳过。
- [x] 子节点排序、递归参数、各级 heuristic cutoff 都使用该候选自己的剩余预算；不可沿用循环外统一减 1。
- [x] 保留完整严格搜索结构；Phase 2 可以作为捷径，不能把全局严格搜索改为只搜索快速两阶段解空间。
- [x] 根据总代价计算 incumbent、upper_bound、返回 depth 和“已排除更短解”的条件。
- [x] 多进程根分支如果过滤了超预算动作，同步修改结果接收数量；当前固定等待 18 项，不能过滤后仍等待 18 项。
- [x] 转置表值表示已排除的剩余代价，保持 last_face 等剪枝上下文；不同 metric 的搜索不共用失配的表内容。
- [x] 保持现有取消、deadline 和多进程失败回退行为。

搜索核心语义示意：

```text
for budget in increasing_budgets(admissible_lower_bound, effective_max):
    search(state, remaining=budget):
        if admissible_heuristic(state) > remaining: reject
        if solved(state): return current_path
        for move in canonical_18_moves:
            next_remaining = remaining - cost(move, metric)
            if next_remaining < 0: continue
            search(apply(state, move), next_remaining)
    只有整层完成且未找到解，才记为 completed_depth
```

已有合法候选总代价为 C 时，只需严格排除到 C−1。若用户预算、超时或取消使该证明未完成，不能仅因候选存在就设置 optimal。

完成条件：串行与多进程 QTM 结果通过独立浅层 oracle 核对；HTM 回归通过。

### 阶段 C：C++ 严格搜索与原生桥接

- [x] 增加请求级 metric 并贯穿 SolverOptions、结果、进度、CLI 和协议。
- [x] 修改 DFS 两条分支（有/无候选排序）及 `split_task`，保存每个候选自己的剩余预算。
- [x] 所有从有符号预算转换为 `uint8_t` 的位置先检查非负，避免 −1 变为 255 造成搜索或剪枝错误。
- [x] 修改候选总代价比较、effective_max、动态 incumbent 更新、完成证明判断和结果 depth。
- [x] 在单次调用中选择有效 Tail 指针：HTM 使用现有表，QTM 使用空指针；不要清空共享已加载表来切换模式。
- [x] 同步检查并行拆分的 Tail 阈值、方向探测和排序阈值。仅影响性能的动作项数阈值可以保留，但需明确其单位。
- [x] 正向/逆向求解都保持代价一致。
- [x] `_validated_result` 除执行动作验证复原外，还核对结果 metric 与请求一致、depth 等于重新计算的总代价。
- [x] 原生返回的模式或步数不匹配时按引擎错误处理，不得静默修饰后信任其最短性标记。
- [x] 原生超时、取消继续使用现有终态处理；超时不重新启动一轮 Python 搜索。

完成条件：CLI 和常驻进程均能处理两种模式；Python/C++ 的最短代价一致；QTM 即使进程已加载 HTM Tail 也不会触发错误捷径。

### 阶段 D：服务、候选和缓存隔离

- [x] `POST /api/solve` 校验并向所有路径传递 metric，包括直接返回零步、短时探测、快速候选、后台证明、原生失败回退。
- [x] 现有快速两阶段生成器可以继续按 HTM 生成候选；服务层使用目标模式重新计价，并标识为候选。此处不宣称快速生成器已经优化了 QTM。
- [x] 若在快速生成器中直接支持 QTM 优化，必须连同两阶段预算与剪枝一起适配，不能只把结果 metric 改成 QTM。
- [x] 服务器、常驻服务控制线程和 C++ 搜索线程接收更优候选时，均按当前 metric 的总代价比较，而非公式项数。
- [x] 活动任务 key 包含状态、魔方阶数、实际最大预算、metric 和 proof_version。
- [x] 原生证明缓存 key 至少包含状态、metric、proof_version。若表/证明规则可在进程内变化，还必须隔离其版本；当前进程内不可变资产可沿用现有生命周期。
- [x] 同模式重试可复用完整排除深度；跨模式一律不复用。首版不实现 HTM/QTM 证明界限转换。
- [x] 排队、原生初始化、搜索与 Python 回退继续共享原始绝对 deadline。
- [x] 结果、任务和进度快照带 metric；状态 complete 与 optimal=true 的含义保持一致。

完成条件：同状态同模式可以复用活动任务；同状态不同模式产生独立任务；切换 HTM→QTM→HTM 时缓存结论不会串用。

### 阶段 E：二阶准确距离表

- [x] 保留现有 DBL 固定规范化、9 列 U/R/F 转移表及面向映射。
- [x] HTM BFS 扩展全部 9 种动作；QTM BFS 仅扩展 `U U' R R' F F'` 六种代价均为 1 的动作。
- [x] BFS 不使用“禁止连续同面”的路径剪枝；状态去重由访问表处理。
- [x] 两种表都覆盖 `7! × 3^6 = 3,674,160` 个规范化状态，距离最大值分别为 11 和 14。
- [x] 磁盘缓存按模式区分，建议保留 `two_by_two_htm_v1.bin`，新增 `two_by_two_qtm_v1.bin`；表头/magic 必须能识别模式并保留校验。
- [x] 实例内的 `_tables` 改为按模式索引，避免先加载 HTM 后请求 QTM 仍命中同一份准确距离。
- [x] 输出路径可以检查全部 9 种动作，选择满足 `distance(next) + cost(move) == distance(current)` 的动作，这样可以直接输出 `R2`。
- [x] 路径恢复改为按剩余代价循环，不能继续使用每次固定减 1 的 `range(depth, 0, -1)`。
- [x] 映射回用户面向后重新执行公式，验证复原并核对总代价。
- [x] 保留 deadline、损坏重建、原子写入和只读部署的内存回退能力。
- [x] 扩展模块 CLI 支持 `--metric HTM|QTM`，省略仍默认 HTM，供打包脚本分别生成两张表。

完成条件：全表覆盖和直径检查通过；随机状态在全部 24 个用户面向下的结果均可复原且最短代价一致。

### 阶段 F：前端选择与异步生命周期

- [x] 在开始求解按钮上方加入“180° 计步方式”：`算一步（HTM）` / `算两步（QTM）`；默认 HTM。
- [x] 请求开始时捕获 cube_size、facelets、metric 和最大预算等快照；后续响应按快照关联，不读取已变化的选择框代替请求参数。
- [x] activeSolveKey 加入 metric 及实际搜索预算，与后端任务区分规则一致。
- [x] 切换 metric 时递增 solveGeneration，取消旧任务、清除轮询、清除旧解和旧最短标记；保留照片、facelets 和人工校正。
- [x] 旧请求迟到时不能覆盖新模式结果；若旧响应才返回 job_id，仍按现有策略取消对应任务。
- [x] 切换后由用户再次点击“开始求解”，避免用户仅切换选项就立即启动高成本搜索。
- [x] 请求中的 max_depth 按阶数/模式选择；页面标题说明、metric 标签、零步结果、候选、证明进度和终态文案同步。
- [x] 进度按任务 metric 展示，例如“QTM：已严格排除 ≤ 12 步”；公式旁解释 `R2` 在该模式下计 2 步。
- [x] 选择控件有可访问标签，并检查窄屏布局。

完成条件：在运行、排队、响应未到达、已完成和超时状态下切换，均不会显示错模式结果；切换不要求重新上传照片。

### 阶段 G：发布资产、文档与基准

- [x] 打包预检分别生成并验证两种二阶表，将它们加入必需资产与复制清单。
- [x] 原生程序与 Python 协议版本同步；沿用现有中文路径和冻结应用根目录规则。
- [x] 更新 README 的计步说明、API、二阶表、最短性状态及搜索上限；更新 Windows 使用说明和 CHANGELOG。
- [x] 扩展基准脚本以显式记录 metric 和加权候选代价，避免默认五字段 HTM 请求误测 QTM。
- [x] 基准每次独立证明，关闭证明缓存复用或为每次测量创建干净原生进程；另行测量缓存重试收益。
- [x] 保存 HTM 改动前后数据，以及 QTM 固定样本的耗时、节点数、已完成预算、成功/超时、冷/热启动和内存。
- [x] 明确是否使用 Tail。QTM 首版的 Tail 禁用属于已知实现选择，不能误记为表未加载。

完成条件：开发环境、原生可用/不可用、便携包资产预检均覆盖双模式；性能报告保留超时样本，不以打乱长度冒充最短长度。

## 6. 必须执行的测试矩阵

将新测试放入现有对应测试模块，或建立职责明确的 `test_metrics.py` / `test_metric_search.py`。以下测试必须验证行为和最短性，不只检查代码里是否出现某个字符串。

| 类别 | 测试与验收标准 |
| --- | --- |
| 基础计价 | 全部 18 种动作，空解、混合公式、逆公式、非法模式；HTM/QTM 结果准确 |
| 真正改变优化目标 | 固定至少一个经独立求解确认的状态，其某条 HTM 最短解按 QTM 计价高于 QTM 最短值；证明实现确实重新优化，而非只改步数 |
| 三阶独立 oracle | HTM 用 18 动作单位代价 BFS；QTM 用 12 种正反 90° 动作单位代价 BFS，允许连续同面；与生产搜索比较浅层准确代价 |
| 下界有效性 | 已有 HTM 启发式在浅层 QTM 状态上不超过 oracle 准确距离；覆盖无 PDB、部分 PDB 和完整 PDB 的相关路径 |
| 预算边界 | `R2` 在 QTM 预算 1 下不能返回最短解，预算 2 下返回代价 2；测试 0、默认上限、较小上限与非法输入 |
| 引擎一致性 | Python 串行、多进程、C++ 单线程/多线程、正向/逆向的结果均能复原，且同模式最短代价一致；不要求公式文本完全相同 |
| 终局表隔离 | C++ 已加载 HTM Tail 时搜索 QTM `R2` 等状态，不允许在 1 步预算内错误命中；HTM Tail 路径继续工作 |
| 候选更新 | 构造两条均可复原的公式，其“项数更少”和“QTM 代价更小”排序不同；QTM 必须选择后者 |
| 协议与返回校验 | 旧 EXE、未知 metric、缺少能力声明、metric/depth 不匹配、无效动作、不能复原的原生输出均被正确处理 |
| 缓存与证明 | 活动任务去重按模式隔离；同一常驻进程交替处理 HTM/QTM；取消后只复用完整排除预算 |
| 生命周期 | 排队/初始化计时、取消、不限时请求、原生故障回退、原生超时不重启搜索、迟到响应 |
| 二阶 | 两张完整表覆盖、直径 11/14、双缓存不混用、缓存损坏重建、24 个面向映射、只读缓存与首次建表超时 |
| 前端 | 默认 HTM、切换 QTM、请求参数、模式标签、加权步数、进度、取消旧任务、拒绝旧响应、保留照片与校正 |
| 发布 | 两张二阶表加入预检和便携包资产，中文路径可读，API 省略 metric 的旧请求继续按 HTM 工作 |

独立 oracle 不得调用被测最短搜索器产生“期望答案”。两种最优公式不同的回归样本必须记录实际状态、独立验证方式、两个最短代价与合法公式；不要临时编造样本或将打乱长度当成最短长度。

完整图遍历可以只在建表/慢测中执行；日常搜索回归选择可重复的浅层集和固定种子。大规模随机三阶实例不要求在固定秒数内完成证明，超时语义仍必须正确。

## 7. 验证命令与执行纪律

以下命令在应用根目录的 PowerShell 中执行。依赖已安装时直接使用，缺失时先报告具体能力缺口。编写本文时尚未执行双模式实现与以下功能验收。

### 7.1 现有工具入口

```powershell
.\.venv\Scripts\python.exe -m pytest -ra tests/test_solver.py tests/test_two_by_two.py tests/test_search_lifecycle.py tests/test_hybrid_api.py
node tests/solver_ui.test.js
.\native\build.ps1
.\.venv\Scripts\python.exe -m pytest -ra -m "native_binary or native_pdb"
.\tests\check.ps1
.\release\build_windows.ps1 -PreflightOnly
git diff --check
git status --short
```

按阶段运行相关子集，功能完成后运行完整检查；不要无理由反复运行耗时全量测试。原生 PDB 缺失时，可按现有 `native/build_tables.ps1 -CiMinimal` 生成必需 HTM 表；QTM 首版不要求生成新的三阶大型表。

`tests/check.ps1` 当前连续运行多个 Node 测试，执行者还应逐个确认退出码，不能只凭末尾 Python 成功推断全部前端测试通过。原生 marker 被跳过也不代表原生能力已验证。

### 7.2 实现新增 CLI 后才可运行

以下 `--metric` 是本任务要求新增的参数，不是编写本文时已有的能力：

```powershell
.\.venv\Scripts\python.exe -m cube_app.two_by_two_tables --metric HTM
.\.venv\Scripts\python.exe -m cube_app.two_by_two_tables --metric QTM
```

原生 CLI、协议和基准脚本增加 metric 后，补上最终可复制的双模式求解与基准命令到交付记录中。使用真实合法 facelets；不要直接复制示例占位符调用。

性能验收至少包含同一批 HTM 样本改动前后对比，以及固定 QTM 样本。固定线程数、超时和资产，区分缓存条件；记录实际完成和跳过项目，不虚构通过数量、加速比或时间承诺。

## 8. 完成定义与交接产物

以下条件全部满足才可宣布双模式功能完成：

- [x] 二阶、三阶均可在 UI 和 API 选择 HTM/QTM，缺省保持 HTM。
- [x] Python 与 C++ 严格搜索按动作总代价优化，独立浅层最短性测试通过。
- [x] HTM PDB 仅作为合规下界复用；QTM 首版不会使用 HTM Tail 直接得出证明。
- [x] 所有候选、结果、预算、进度、任务与证明缓存遵循相同 metric。
- [x] 二阶双距离表生成、校验、缓存和打包完成适配。
- [x] HTM 回归、原生验证、API/生命周期与前端测试已实际执行；未执行项明确列出。
- [x] README、Windows 说明、CHANGELOG 与实际实现一致。
- [x] 提供性能记录和 QTM 使用较弱下界的实际限制，不宣称所有状态都能在默认超时内证明。

最终交付报告包含：修改文件与行为、计价/协议/缓存约定、实际测试命令和结果、性能数据、环境导致未验证的部分。仅完成界面或返回值计数时，不能将本任务标为完成。

如因原生编译环境、PDB 或依赖缺失而无法验证，保留已完成实现，明确列出缺口和恢复步骤；不得以自动跳过测试替代验收。

## 9. 后续优化边界

正确性与功能交付后，只有实际基准显示需要时，再设计 QTM 专用三阶剪枝表、加权终局表、候选排序或安全的奇偶性优化。新表必须具有独立 metric、格式版本、覆盖深度、校验及生成测试。

不要用“需要重新生成所有 PDB”阻塞双模式基础功能，也不要为了提前提高速度引入未证明安全的剪枝。

## 10. 数学界限参考

- [三阶 QTM 最大最短距离为 26；同时说明 HTM/QTM 定义](https://www.cube20.org/qtm/)。
- [二阶全状态数量及 HTM 11 / QTM 14 的距离分布](https://www.jaapsch.net/puzzles/cube2.htm)。

实现的正确性仍需由本项目独立测试和实际复原验证确认。上述资料提供数学界限，不代表本项目已经具备对应实现或运行性能。

## 11. 实施交付记录（2026-09-28）

### 开始前基线

- 基线源码提交：`ae73ca81af1ed077c059f3345377190bf0ce2882`。工作区原有未跟踪 `.codex/` 与本指南均保留，未提交或发布。
- 未发现适用 `AGENTS.md`。
- 执行 `.\.venv\Scripts\python.exe -m pytest -ra tests/test_solver.py tests/test_two_by_two.py tests/test_search_lifecycle.py tests/test_hybrid_api.py`：27 passed。
- 执行 `node tests/solver_ui.test.js`：passed。
- 原有环境警告：`.pytest_cache` 权限导致 pytest 缓存写入失败，不影响上述测试结果；后续检查使用可写缓存目录。
- 原生性能基线：`docs/benchmarks/htm-before.json`，4 线程、每样本 2 秒、1 次重复、staged、独立证明；记录 EXE/PDB SHA256、build-info、冷启动与进程峰值内存。`repo14` 与 `pgo16` 均完成 HTM 最短性证明。
- 基线命令：`.\.venv\Scripts\python.exe tests/benchmark_native.py --cases repo14,pgo16 --threads 4 --timeout 2 --repeats 1 --variants staged --output docs/benchmarks/htm-before.json`。

### 阶段进展

- 已开始 A/B/C/E/F 并行实现，D 服务层任务 key 使用 `(facelets, 3, max_depth, metric, proof_version=2)`；快速 HTM 候选按请求模式重新计价，候选更新比较总代价。
- D 初步验证：`tests/test_metric_api.py tests/test_search_lifecycle.py tests/test_hybrid_api.py` 共 37 passed；覆盖双模式计价、默认预算、非法参数、任务隔离、候选排序、同 deadline 回退、超时不重启与取消快照。
- 非最短终态新增 `budget_exhausted`，不得标记 `proof_status=complete`；候选仍可执行。完整验收结果将在实现完成后补充。

- A/B 验证：`pytest -ra tests/test_metrics.py tests/test_metric_search.py tests/test_solver.py -p no:cacheprovider`：50 passed；独立 BFS 允许连续同面，HTM/QTM 浅层代价≤3的规范化剪枝与完整动作图一致；真实多进程 QTM 回归通过。
- E 验证：两表各覆盖 3,674,160 状态、直径 HTM11/QTM14，二阶测试 9 passed；独立 meet-in-the-middle BFS 固定反例确认 HTM7 的一条公式按QTM计10，而 QTM 严格最短8，证明并非仅重计价。

- C 最终编译及专项验收：原生模块 24 passed，另补真实 QTM 取消→同模式重试→跨模式隔离 1 passed；无 PDB / 部分 / 完整 PDB、单/多线程、正逆方向、已加载 HTM Tail 与协议能力检查均实际执行。EXE SHA256 `0823726B72C8975A89CD208D1DAAAA0D2DB25CC6FEB1587F7629C73C75D4F67C`。
- D 最终 API 专项：27 passed，包含真实二阶双模式、Python 与原生 QTM R2 预算1 不误报状态非法 / 不误报最短；任务 / 取消 / 进度模式和候选代价核对。
- E 最终：11 passed，新增锁等待deadline和QTM R2单项公式的剩余预算减2验证。
- F 最终：Node solver UI passed，真实应用函数驱动请求/轮询；覆盖迟到POST/GET、queued/running/complete/timeout/budget_exhausted切换、无候选超时文案、保留照片和校正。实际390×844浏览器检查无横向溢出，截图 `docs/benchmarks/qtm-mobile.png`。
- G 预检：`release/build_windows.ps1 -PreflightOnly` exit0，双表覆盖/直径与原生真实ready协议3/proof2双模式能力校验通过。基准同参数before/after及QTM报告已保存；另有 `tests/benchmark_metric_cache.py` 与 `docs/benchmarks/cache-retries.json` 测同进程独立模式缓存重试。完整check运行中。

### 最终验收与交付

- 执行 `tests/check.ps1`，环境设置 `PYTEST_ADDOPTS=-o cache_dir=.cache/pytest-cache`、`REQUIRE_NATIVE_BINARY=1`、`REQUIRE_NATIVE_PDB=1`：exit0。4 个 Node 前端入口逐一通过且分别检查退出码，Ruff 通过，全部 Python **146 passed / 73.30s、无跳过**，Python compileall 通过。
- 原生模块最终包含 **25** 项测试，原生 binary/PDB 标记在上述全量检查中实际运行，没有以自动跳过替代验收。
- `git diff --check` 通过；原有未跟踪 `.codex/` 保留。没有提交、推送、打标签或发布；便携包仅完成双模式资产适配与预检，没有构建新版本ZIP。
- 双模式基准、最终源码/EXE/PDB哈希、冷/热启动、节点、完成预算、内存及超时样本已保存；最终EXE与after及cache报告的SHA256一致。
- 详细文件行为、协议3/proof2、缓存规则、独立oracle反例、性能表、限制和可复制CLI/基准命令见 [`htm-qtm-delivery.md`](htm-qtm-delivery.md)。
- 已完成指南要求的开发环境、原生可用/不可用、二阶双表、API/lifecycle、前端和Windows资产预检。未执行实际便携包冻结/压缩和发布，也未生成后续优化范围的QTM专用三阶大型PDB/Tail。
- QTM复杂三阶状态可能超时；预算26不承诺在默认时限内证明。保存的pgo16 QTM样本在2秒内超时，仅返回候选代价21并完整排除到16，未宣称最短。

### 后续发布（用户明确授权）

- 版本增加至1.5.0，更新版本源/包元数据/CHANGELOG/两份README。补C++格式门禁后重编译，通过完整146测试及75.45%覆盖率门禁。
- Windows实际便携包构建与冻结运行四条双模式复原冒烟验证通过，证据 `docs/release-v1.5.0.json`；发布状态以GitHub v1.5.0 Release及CI结果为准。前述“未构建/未推送”均为首次功能交付时状态。
