# Rubic Photo Solve：二阶 / 三阶魔方拍照识别与最短解

这是一个运行在本机浏览器中的魔方求解器：选择二阶（2×2）或三阶（3×3），上传六个面的照片，确认识别出的色块，再生成可执行的复原步骤，并在条件允许时继续验证 HTM 严格最短解。

本仓库的实际应用目录是 [`魔方拍照解/`](./魔方拍照解/)。本文档是仓库入口说明；进入该目录后可以直接运行所有脚本。更细的模块说明、API 字段和排障步骤也同步写在 [`魔方拍照解/README.md`](./魔方拍照解/README.md)。

当前版本以 `cube_app.__version__` 和运行时 `GET /api/version` 的返回值为准。版本、变更记录和发布方式见[版本与发布](#版本与发布)。

## 目录

- [功能概览](#功能概览)
- [快速开始](#快速开始)
- [用户操作流程](#用户操作流程)
- [拍摄与六面方向约定](#拍摄与六面方向约定)
- [求解结果如何解读](#求解结果如何解读)
- [项目结构](#项目结构)
- [API 接口速览](#api-接口速览)
- [原生求解器与剪枝表](#原生求解器与剪枝表)
- [开发、测试与基准](#开发测试与基准)
- [版本与发布](#版本与发布)
- [故障排查与限制](#故障排查与限制)

## 功能概览

- 本地网页界面：服务默认只监听 `127.0.0.1`，照片和识别数据不会上传到云端。
- 二阶识别与求解：没有中心块，自动从 24 个色块恢复 6 种颜色，并按 HTM 求严格最少步数。
- 三阶识别与混合求解：先返回可执行的快速解，再在后台逐深度验证更短解；验证完成后自动替换为严格结果。
- 多候选视觉检测：OpenCV 检测器返回候选四角、置信度和质量信息；浏览器检测器可作为降级路径。
- 人工校正：可旋转单面网格、拖动四角透视区域、修改非中心色块颜色。
- Windows 便携发布：发布 ZIP 自带运行所需的应用文件、OpenCV、C++ 求解器和基础 PDB 表。

> 快速解可以立即执行，但在 `proof_status` 变为 `complete` 之前，不应把它称为已经证明的最短解。

## 快速开始

先选择适合你的使用方式：

| 目标 | 推荐方式 | 是否需要 Python | 是否需要 C++ 编译器 |
| --- | --- | --- | --- |
| 直接拍照并求解 | Windows 便携版 | 否 | 否 |
| 阅读或修改 Python/前端代码 | 源码运行 | 是，3.10–3.14 | 否 |
| 构建原生求解器或发布包 | 开发环境 | 是，3.10–3.14 | 构建原生核心时需要 |

以下源码命令均在 `魔方拍照解` 目录执行。若当前位于仓库根目录，先运行：

```powershell
Set-Location .\魔方拍照解
```

### Windows 便携版（普通用户推荐）

1. 从 GitHub Releases 下载 `RubicPhotoSolve-X.Y.Z-windows-x64.zip`。确认下载的是 ZIP，不是 “Source code”。
2. 在资源管理器中右键 ZIP，选择“全部解压”。不要直接在压缩包预览窗口运行程序。
3. 把完整目录放在普通可写位置，例如桌面或文档目录。路径可以包含中文和空格。
4. 打开解压后的目录，确认至少存在 `RubicPhotoSolve.exe`、`启动魔方求解器.cmd`、`VERSION.txt` 和 `_internal/`。
5. 双击 `启动魔方求解器.cmd`。第一次启动被 Windows 安全提示拦截时，先确认文件来自本项目 Release，再选择允许运行。
6. 保持命令行窗口打开。看到类似下面的输出说明服务已启动：

   ```text
   魔方最短解应用 1.3.1 已启动: http://127.0.0.1:8765/
   ```

7. 浏览器通常会自动打开；没有自动打开时，把终端打印的完整地址复制到浏览器。
8. 按照[用户操作流程](#用户操作流程)上传六面并求解。
9. 使用结束后回到命令行窗口按 `Ctrl+C`。浏览器标签页关闭后，后台服务仍会继续运行，必须关闭终端或按 `Ctrl+C` 才会停止。

便携包通常包含 `RubicPhotoSolve.exe`、`web/`、`cube_solver.exe`、corner / phase-1 PDB、`VERSION.txt` 和 `README-Windows.txt`。如果某个原生文件或 PDB 缺失，服务会安全回退到 Python 求解器，通常只影响速度。

### 从源码运行

#### 第 1 步：检查 Python

要求 Windows、Python 3.10–3.14：

```powershell
python --version
```

预期输出形如 `Python 3.14.4`。若命令不存在，请安装受支持版本的 Python，并在安装器中启用 “Add Python to PATH”。

#### 第 2 步：创建虚拟环境

```powershell
python -m venv .venv
```

成功后目录中会出现 `.venv`。如果 `ensurepip` 失败，可直接使用项目现有的可用 Python 环境继续，但不要混用多个 Python 安装。

#### 第 3 步：激活虚拟环境

```powershell
.\.venv\Scripts\Activate.ps1
```

PowerShell 提示符前通常会出现 `(.venv)`。若执行策略阻止脚本，只对当前窗口临时放行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

#### 第 4 步：安装运行依赖

```powershell
python -m pip install -r requirements.txt
```

依赖安装完成后可检查版本：

```powershell
python -c "import cv2, numpy; print(cv2.__version__, numpy.__version__)"
```

#### 第 5 步：启动服务

```powershell
python server.py
```

服务默认端口为 `8765`；若被占用，会在 `8765`–`8794` 中寻找可用端口。始终使用终端实际打印的地址。

#### 第 6 步：验证服务

新开一个 PowerShell 窗口，根据实际端口执行：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/version
```

预期返回 `ok=True`、`version=1.3.1`。随后用浏览器打开同一地址的根路径。

#### 第 7 步：停止服务

回到运行 `python server.py` 的窗口按 `Ctrl+C`。不要直接结束整个 Python 安装目录中的其他进程。

OpenCV 用于后端照片定位；没有 OpenCV 时服务仍能启动，但 `/api/detect` 会返回 `503`，前端可使用浏览器检测器或人工四角校正。

### 开发环境

#### 第 1 步：建立开发环境

```powershell
.\setup-dev.ps1
```

该脚本会创建或复用 `.venv`，安装锁定的开发依赖，并以 editable 模式安装项目。

#### 第 2 步：确认工具可用

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pytest --version
node --version
```

前端测试需要 Node.js 20 或兼容版本。只开发 Python 核心时可以暂时不安装 Node，但完整检查会失败。

#### 第 3 步：运行完整检查

```powershell
.\tests\check.ps1
```

看到 `31 passed, 3 skipped` 一类结果是正常的；实拍素材不存在时会跳过 3 个 real-image 测试。

#### 第 4 步：安装发布依赖（仅打包时需要）

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-release.txt
```

## 用户操作流程

### 第 1 步：固定魔方的空间基准

先决定哪一面作为 `F`（前面），并在整个拍摄过程中保持这个基准。不要每拍一张就随意改变对“前、上、右”的定义。

### 第 2 步：选择魔方类型

页面顶部选择 `2×2` 或 `3×3`。二阶每面 4 个色块，三阶每面 9 个色块。切换类型会改变识别网格、颜色数量校验和求解器。

### 第 3 步：按约定拍摄六面

依次拍摄 `U`、`R`、`F`、`D`、`L`、`B`。每张照片都从该面的外侧正对拍摄，并按照下方[面标签与相邻边](#面标签与相邻边)规定的边朝上。

### 第 4 步：上传到正确位置

点击页面中相应面卡片上传照片。不要根据贴纸颜色猜标签：`U/R/F/D/L/B` 表示空间位置，不表示白、红、绿等固定颜色。

### 第 5 步：检查四角定位

确认覆盖框的四个角落在魔方面的四个外角，网格线大致穿过色块间隙。如果框选偏离：

1. 点击该面右上角的 `⌗`；
2. 在原图上拖动四个角；
3. 让四边贴合魔方面外边缘；
4. 点击应用并重新检查网格。

### 第 6 步：校正单面旋转方向

把识别网格与方向表对照。若照片整体旋转了 90°、180° 或 270°，点击旋转按钮，直到相邻边方向正确。颜色看起来正确并不代表空间方向正确。

### 第 7 步：校正颜色

逐格检查识别结果。点击识别错误的非中心色块，选择正确颜色。三阶中心块固定为该面的颜色基准；二阶没有中心块，必须依靠六面全局聚类和角块合法性确定颜色。

### 第 8 步：等待状态校验通过

六面齐全后，确认每种颜色数量正确且页面没有非法角块、非法棱块或方向错误提示。若状态非法，优先检查照片方向，其次检查四角定位，最后才逐格改色。

### 第 9 步：设置求解参数并开始求解

一般保持默认最大深度。三阶可以调整“最短验证超时”：较短时间更快结束证明，较长时间更可能完成严格最短证明，但会占用更多 CPU 时间。

### 第 10 步：正确理解结果

- 二阶通常同步返回 `proof_status=complete` 的严格最短解；
- 三阶可能先返回 `optimal=false` 的快速解，该解可执行但尚未证明最短；
- 页面会继续轮询后台任务；完成后显示严格结果；
- `timeout` 表示证明时间用完，不表示快速解错误；
- `cancelled` 表示用户取消或任务被终止；已有快速解仍可保留。

### 第 11 步：执行转动

始终以已选定的 `F` 面作为前面、`U` 面作为上面执行公式。`R` 表示右面顺时针，`R'` 表示右面逆时针，`R2` 表示右面转 180°；其他字母同理。顺逆时针均以正对该面的视角判断。

## 拍摄与六面方向约定

### 拍摄建议

从对应面的外侧尽量正对拍摄，保证九个贴纸可见；光线均匀，避免强反光、阴影、遮挡和相似方形背景。魔方不必填满画面，也不要求图片为正方形；魔方较小时应靠近拍摄或直接使用四角校正。

### 面标签与相邻边

| 标签 | 含义 | 拍摄时朝上/基准 |
| --- | --- | --- |
| `U` | 上面 | `B` 边朝上，即 `F` 边朝下 |
| `R` | 右面 | `U` 边朝上 |
| `F` | 前面 | `U` 边朝上；也是解法前面 |
| `D` | 下面 | `F` 边朝上 |
| `L` | 左面 | `U` 边朝上 |
| `B` | 后面 | `U` 边朝上 |

方向不同请旋转该面的网格。六张独立照片可能存在多个空间方向解释，应用不会在有歧义时静默猜测。若更换前面基准，应把目标面放到 `F`，并按真实相邻关系重新放好其他五面。

## 求解结果如何解读

### HTM 计步

项目使用 HTM（Half Turn Metric）：`R`、`R'` 和 `R2` 各计 1 步。结果中的 `depth` 是 HTM 步数，`solution` 是空格分隔的转动记号。

### 二阶（2×2）

二阶没有中心块。应用会把 24 个采样色块聚成 6 组、每组 4 个，再利用 8 个角块的颜色组合和朝向约束确定颜色标签。求解器只建模角块排列与扭转，把整体旋转的 24 种空间朝向视作同一个复原状态，按深度递增 IDA* 搜索，最大深度为 11；返回时 `proof_status` 为 `complete`。

### 三阶（3×3）

三阶采用混合流程：

```text
输入 facelets
    ├─ 短时严格探测 ─ 找到证明解 ─ 直接返回 complete
    └─ 快速求解 ─ 返回候选解 ─ 后台 IDA* / C++ 核心继续证明
                              ├─ complete：严格最短已证明
                              ├─ timeout：候选可用，但未完成证明
                              └─ cancelled / error：任务被取消或失败
```

后台按深度从小到大，只搜索比当前候选更短的深度。超时表示证明尚未完成，不代表候选解错误；极难状态的严格证明可能耗时较久。

## 项目结构

```text
魔方拍照解/
├─ server.py                 # 本地 HTTP 服务、API 路由、任务队列和静态文件
├─ windows_launcher.py       # Windows 启动器
├─ cube_app/                 # 视觉、颜色、面贴纸、二阶和三阶求解核心
├─ web/                      # index.html、app.js、styles.css
├─ native/                   # C++20 求解器、头文件和剪枝表脚本
├─ tests/                    # Python、Node、API、视觉和原生测试
├─ release/                  # 版本检查、Windows 打包和发布前检查
├─ requirements*.txt        # 运行、开发、发布依赖锁定
├─ pyproject.toml            # 包元数据、版本配置和工具配置
└─ CHANGELOG.md              # 版本变更记录
```

关键模块：

- `cube_app/vision.py`、`detection.py`：图像解码、四角候选、透视区域和九宫格采样；
- `cube_app/color.py`、`cubie.py`：颜色分配、合法状态校验和面贴纸到角棱块转换；
- `cube_app/fast.py`、`optimal.py`、`two_by_two.py`：快速、三阶严格和二阶求解；
- `cube_app/native.py`、`runtime.py`：原生 EXE / PDB 资产调用与源码 / PyInstaller 路径解析；
- `server.py`：提供静态页面、识别接口、求解接口和后台任务状态；
- `web/app.js`：上传、校正、求解、轮询和结果展示。

## API 接口速览

服务默认绑定 `127.0.0.1`。下例假设端口为 `8765`，实际端口以启动日志为准。

### `GET /api/version`

返回当前服务版本：

```json
{"ok": true, "version": "1.3.1"}
```

### `POST /api/detect`

```json
{"image": "data:image/jpeg;base64,...", "cube_size": 3}
```

成功时返回 `detected`、`corners`、`confidence`、`method`、`quality`、候选列表和 `fallback_used`。OpenCV 不可用返回 `503`；请求或图片无效通常返回 `400`。

### `POST /api/solve`

```json
{
  "facelets": "...",
  "cube_size": 3,
  "max_depth": 20,
  "timeout_seconds": 180
}
```

`facelets` 只允许使用 `U R F D L B` 六个字符，并按 `U`、`R`、`F`、`D`、`L`、`B` 顺序拼接。三阶每面 9 个字符，共 54 个；二阶每面 4 个字符，共 24 个。三阶还要求六个中心位置分别是对应面标签，且每种字符数量必须正确。

`cube_size` 只能是 `2` 或 `3`；`max_depth` 为 `0`–`20`（二阶内部最多 11）；`timeout_seconds` 为 `0.1`–`3600`，传 `0`、`null` 或 `"none"` 表示不设置超时。二阶通常同步返回严格结果；三阶可能返回 `job_id` 和 `proof_status: "queued"`。

### `GET /api/solve/{job_id}` 与 `POST /api/solve/{job_id}/cancel`

前者查询后台任务，后者请求取消任务。任务不存在返回 `404`；排队任务会返回 `queue_position`。

## 原生求解器与剪枝表

需要从源码构建原生加速时，准备 MSYS2 UCRT64 或其他可用的 C++20 `g++`：

```powershell
.\native\build.ps1
.\native\build_tables.ps1
```

脚本依次尝试 `-Compiler`、`CXX` 环境变量和 `PATH`。默认资产写入 `.cache/native/`，以只读内存映射加载并进行完整校验；缺失或损坏时服务回退到 Python 实现。

CI 最小资产：

```powershell
.\native\build_tables.ps1 -CiMinimal
```

实验性完整六棱块库会增加磁盘和内存占用，默认不加载：

```powershell
.\native\build_tables.ps1 -IncludeEdgePdbs
$env:CUBE_NATIVE_EDGE_PDBS = "1"
python server.py
```

## 开发、测试与基准

一键运行完整检查：

```powershell
.\tests\check.ps1
```

分项运行：

```powershell
node tests\recognition.test.js
node tests\color.test.js
node tests\two_by_two_color.test.js
node tests\solver_ui.test.js
python -m pytest -ra
python -m compileall cube_app server.py windows_launcher.py
python release\check_version.py --tag v1.3.1
```

CI 对 `cube_app` 和 `server.py` 执行至少 70% 的分支覆盖率门禁；依赖本地 EXE/PDB 或实拍图片的用例会在资源缺失时跳过。视觉标注基准使用：

CI 中的 `SKIPPED` 不等于失败：Linux Python 矩阵会跳过需要 Windows 原生程序的用例，这些能力由独立的 `Native solver (Windows / UCRT64)` 作业验证；缺少 `tests/initial/` 完整实拍组时，real-image 用例也会跳过。判断失败应看最后的 `FAILED`、`ERROR` 和退出码。

本地复现 CI 覆盖率门禁：

```powershell
.\.venv\Scripts\python.exe -m pytest -ra `
  -m "not native_binary and not native_pdb and not native_slow and not vision_real" `
  --cov=cube_app --cov=server --cov-branch `
  --cov-report=term-missing --cov-fail-under=70
```

视觉标注基准使用：

```powershell
python tests\benchmark_vision.py tests\vision_annotations.json
```

求解性能基准使用：

```powershell
python tests\benchmark_solver.py --timeout 30
```

## 版本与发布

版本只在 `魔方拍照解/cube_app/__init__.py` 中维护：

```python
__version__ = "X.Y.Z"
```

使用语义化版本 `MAJOR.MINOR.PATCH`。修复问题增加 `PATCH`，兼容的新功能增加 `MINOR`，不兼容变更增加 `MAJOR`。

### 第 1 步：确定版本号

```powershell
python -c "from cube_app import __version__; print(__version__)"
git tag --list "v*" --sort=-version:refname
```

不要移动已经推送的标签。旧版本发布后发现问题，应创建新的补丁版本。

### 第 2 步：修改版本和变更记录

1. 在 `cube_app/__init__.py` 修改唯一版本源；
2. 在 `CHANGELOG.md` 增加同版本条目；
3. 更新 README 中的版本示例；
4. 不要在 `pyproject.toml` 添加第二份静态版本。

### 第 3 步：刷新本地包元数据

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

### 第 4 步：验证版本和完整测试

```powershell
.\.venv\Scripts\python.exe release\check_version.py --tag v1.3.1
.\tests\check.ps1
```

### 第 5 步：审查并提交

```powershell
git status --short
git diff --check
git diff
git add -- ..\README.md README.md CHANGELOG.md cube_app\__init__.py tests\test_runtime.py tests\test_two_by_two.py
git diff --cached
git commit -m "Fix Linux CI and release v1.3.1"
git status --short
```

这些路径对应当前 `v1.3.1` 修复。以后发布时应按 `git status` 列出的实际改动调整文件列表。`git diff --cached` 用于最后确认待提交内容；最后一条 `git status --short` 应无输出。

### 第 6 步：构建并创建本地标签

```powershell
.\release\prepare_release.ps1 -CreateTag
```

脚本要求干净工作区，并依次完成版本检查、测试、Windows ZIP 构建、哈希计算和标签创建。`-AllowDirty` 只适合临时验证，不能与 `-CreateTag` 同时使用。

### 第 7 步：检查产物

```powershell
Get-Item .\dist\RubicPhotoSolve-1.3.1-windows-x64.zip
Get-FileHash .\dist\RubicPhotoSolve-1.3.1-windows-x64.zip -Algorithm SHA256
git show --no-patch v1.3.1
```

### 第 8 步：推送并等待发布

```powershell
git push origin main
git push origin v1.3.1
```

只有 `v*` 标签推送会触发 GitHub Release。依次在 Actions 页面确认 Version、Lint、Python、Frontend、Native Windows 和 Publish Release 成功；任一前置任务失败时不会创建 Release。

## 故障排查与限制

- **PowerShell 禁止运行脚本**：执行 `Set-ExecutionPolicy -Scope Process Bypass`，只对当前窗口临时放行。
- **`No module named pytest`**：运行 `.\setup-dev.ps1`，之后使用 `.\.venv\Scripts\python.exe -m pytest`。
- **服务无法启动**：确认 Python 3.10–3.14、依赖安装成功，并使用启动日志中的实际端口。
- **`/api/detect` 返回 503**：后端 OpenCV 不可用；检查依赖，或使用浏览器检测器和人工四角校正。
- **识别方向 / 颜色错误**：先检查相邻边约定，再做四角校正、旋转网格、手动改色或重新拍摄。
- **原生 EXE / PDB 缺失**：运行 `native\build.ps1` 和 `native\build_tables.ps1`；没有 C++ 编译器时可继续用 Python 求解器。
- **`WinError 5`**：受限 Windows 不能创建 worker 时，Python 严格求解器会自动回退到单进程，结果语义不变但可能变慢。
- **三阶未证明**：检查 `/api/solve/{job_id}` 的 `status` 和 `proof_status`；超时、排队和取消都不会把候选解自动标记为最短。
- **发布脚本提示工作区不干净**：先用 `git status --short` 和 `git diff` 审查改动，需要发布的内容必须先提交；正式创建标签时不要用 `-AllowDirty` 绕过保护。
- **标签已创建但没有 GitHub Release**：本地标签必须执行 `git push origin vX.Y.Z`；随后检查 Actions 的前置作业，任何失败都会使 Publish Release 跳过。
- **CI 出现 `SKIPPED`**：跳过本身不是失败；继续查看日志末尾真正的 `FAILED`、`ERROR` 和退出码。

项目面向单机、单用户和本地浏览器，不提供账号、TLS、远程多用户隔离或生产级队列。严格三阶证明可能需要较长时间和较大内存；真实照片效果取决于光照、反光、遮挡和拍摄方向。
