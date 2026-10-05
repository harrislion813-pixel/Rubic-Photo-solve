# 开发与维护门禁

## 环境与运行

Windows 使用 PowerShell 7、Python 3.10–3.14（正式验收使用 3.12）和 Node.js 20 或以上。执行：

```powershell
.\setup-dev.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements-release.txt
```

`pyproject.toml` 与 `requirements-dev.txt` 固定 pytest、pytest-cov、Ruff 和运行依赖，`package-lock.json` 固定 Playwright 1.63.0 及对应 Chromium。`tests/check_environment.py` 在收集验收证据前核对已安装版本，记录 Python、平台、锁文件 SHA-256，以及 pytest/pluggy/coverage 等实际版本。版本漂移会使本地门禁与 CI 失败；不要沿用旧环境生成新的正式验收记录。

按 README 的源码安装步骤准备 HTM 原生程序、完整 PDB 与小表；需要完整 QTM 验收时再准备其独立强表。之后执行：

```powershell
.\tests\check.ps1
```

本地门禁依次执行环境/版本检查、四组前端检查、Ruff、全部 pytest、真实浏览器实拍求解回放、仓库体积检查和 Python 编译。运行证据放在忽略的 `artifacts/`；pytest 的原始照片集合在存在时仍会使用。缺失原始 `initial/` 不会使新的实拍浏览器门禁跳过：它使用已跟踪的 12 张样本（约 2.44 MiB），依赖缺失直接失败。

CI 的 Windows 原生任务编译并准备 HTM 资产后运行同一实拍门禁，设置 `REQUIRE_VISION_REAL=1`，保留浏览器版本、实际输入、截图、公式与回放记录为 artifact。Python 3.12 的稳定覆盖率组纳入 `cube_app.service`，保持原来的 70% 门槛；其余 Python 版本、原生 HTM/QTM 和前端任务继续独立运行。

## 实拍与发布验收的边界

`tests/verify_next_speed_photos.cjs` 的默认 `recognition` 模式仍阻断全部求解请求并断言请求数为零，用于历史性能矩阵。提交级使用：

```powershell
npm run test:photos
```

`--mode=e2e --manifest=tests/fixtures/vision/manifest.json` 放行真实页面求解。门禁要求后端检测成功、自动面贴串与人工参考逐格相同，再通过页面点击提交真实输入，并独立回放初始公式、任务结果、候选和含公式的事件，核对 HTM 步数。二阶、三阶均覆盖；提交级不要求证明严格最短。最长边缩放由产品流程执行，保真度由实际识别结果保证。

发布阶段另用 `tests/verify_release_smoke.py --htm-photos`，在全新解压的便携包上校验资产、HTM/QTM 两种计步和二阶/三阶 HTTP 还原，并保留 `initial-1=18`、`initial-12=17` 的精确最短深度与多来源公式回放。其他照片在 30 秒内是否能证明最短不构成提交级条件。

## 源码与服务兼容

活动引擎位于 `cube_app/solvers/{htm,qtm}` 和 `native/{htm,qtm}`。已删除顶层 7 个历史 Python 模块、旧 `native/{src,include}` 及旧构建脚本；保留 6 个共享模块。`benchmark_solver.py` 测量活动 HTM Python 引擎，缓存为 `.cache/htm`；`benchmark_native.py` 测量显式指定或默认的 `native/htm/build/cube_solver_htm.exe`，其资产来自 `assets/htm/v1`。历史记录的旧程序/缓存不因 import 迁移而变成可直接比较的新基线，原生报告仍需记录程序和资产 SHA-256。冻结源码检查必须显式指定 `--h0` 历史 checkout，必要时以 `--h1` 指定历史 HTM 树。

`release/source_layout.py` 是源码 ZIP 与应用源码溯源共用的允许清单。应用源码清单包含共享模块、选定引擎、提取后的服务模块、启动入口与 Web 文件；HtmFull 不为 QTM 模块背书。该字段表达参与冻结构建的源码，不表示这些 `.py` 文件以散文件交付。GitHub 自动源码包继续由独立 `.gitattributes` 的 `export-ignore` 保护，历史路径排除作为防御配置保留。验收检查具体文件路径，不固定 ZIP 条目数。

`server.py` 保留原有公开名称和函数签名作为兼容入口；HTTP、任务生命周期与求解编排分别位于 `cube_app/service/http_api.py`、`jobs.py`、`solving.py`。`Dependencies` 每次读取入口的实时命名空间，因此替换 `server.BROKER`、求解器或测试补丁仍能到达服务实现。任务在准入时固定自己的 broker，避免后续整体替换使资源归还到错误对象。兼容测试同时验证名称超集和替换行为；候选预算、取消、截止时间、终态提交与原生线程更新的同步逻辑保留。

## 证据与体积

历史原件见[归档索引与恢复命令](evidence-archive-2026-10-06.md)。新运行的大 JSON、图片、压缩包和覆盖率记录放在 `artifacts/`，仅把必要摘要纳入版本库。已跟踪的小型 JSON 与人工参考图继续保留；恢复的历史原件不应重新提交。

体积门禁对版本化工作区要求单文件 ≤ 5 MiB、`docs` 总量 ≤ 20 MiB，当前无例外。迁移先启用带精确哈希例外的单文件门禁，归档验证后才启用总量限制。报告另列 Git 对象存储，普通删除不保证 clone 缩小；本次没有重写历史。

## 任务完成后的固定收尾

验收通过后，先保存交付 ZIP、校验信息、必要日志和验收 JSON，再清理本次创建且已不需要的构建目录、重复解压目录、重复下载和恢复验证副本。`.gitignore` 只控制入库，不释放磁盘；完成报告同时核对实际目录体积。

新任务的临时副本集中在 `artifacts/<task>/temporary/`，交付物和证据放在同级其他目录。清理前逐个核对绝对路径、归属与边界，检查已跟踪文件和链接；保留原始输入、运行资产、开发环境及可复用缓存。具体收尾约束见项目 `AGENTS.md`。

清理全新解压验收目录前，将其独有的 `acceptance.json` 移到保留目录。收尾必须报告释放空间和仍保留的大文件用途；失败或尚未完成验收时保留诊断资料并说明原因。
