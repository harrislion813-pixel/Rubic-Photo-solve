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

以下命令均在 `魔方拍照解` 目录执行。若当前位于仓库根目录，先运行：

```powershell
Set-Location .\魔方拍照解
```

### Windows 便携版（普通用户推荐）

1. 下载 `RubicPhotoSolve-X.Y.Z-windows-x64.zip`，完整解压到可写目录。
2. 双击 `启动魔方求解器.cmd`。
3. 等待窗口打印实际地址，例如 `http://127.0.0.1:8765/`；启动器通常会自动打开浏览器。
4. 上传六个面、检查识别并开始求解。
5. 关闭应用时回到命令行窗口按 `Ctrl+C`。

便携包通常包含 `RubicPhotoSolve.exe`、`web/`、`cube_solver.exe`、corner / phase-1 PDB、`VERSION.txt` 和 `README-Windows.txt`。如果某个原生文件或 PDB 缺失，服务会安全回退到 Python 求解器，通常只影响速度。

### 从源码运行

要求 Windows、Python 3.10–3.14：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python server.py
```

服务默认端口为 `8765`；若被占用，会在 `8765`–`8794` 中寻找可用端口并打印实际端口。OpenCV 用于后端照片定位；没有 OpenCV 时服务仍能启动，但 `/api/detect` 会返回 `503`，前端可使用浏览器检测器或人工四角校正。

### 开发环境

```powershell
.\setup-dev.ps1
```

该脚本会创建或复用 `.venv`，安装锁定的开发依赖，并以 editable 模式安装项目。构建 Windows 发布包前再安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-release.txt
```

## 用户操作流程

1. **选择类型**：页面顶部选择 `2×2` 或 `3×3`。
2. **上传六面**：按 `U R F D L B` 位置上传；`F` 是输出解法的前面基准。
3. **检查定位**：确认四角、九宫格和置信度；区域偏移时点击 `⌗` 拖动四角。
4. **校正颜色**：旋转网格，或点击非中心色块手动改色。中心块固定为该面的标签。
5. **开始求解**：二阶通常直接得到严格解；三阶可能先显示快速解，再等待后台证明。
6. **查看状态**：页面约每秒轮询一次；超时或取消时保留已有候选，但显示“未证明”。

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
{"ok": true, "version": "1.3.0"}
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
python release\check_version.py --tag v1.3.0
```

CI 对 `cube_app` 和 `server.py` 执行至少 70% 的分支覆盖率门禁；依赖本地 EXE/PDB 或实拍图片的用例会在资源缺失时跳过。视觉标注基准使用：

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

发布步骤：

1. 更新 `__version__` 和 `CHANGELOG.md`；
2. 运行 `python release\check_version.py`；
3. 提交全部修改；
4. 运行 `.\release\prepare_release.ps1 -CreateTag`，由脚本执行检查、测试、构建并创建 `vX.Y.Z` 标签；
5. 推送 `git push origin vX.Y.Z`，CI 在所有检查通过后创建 GitHub Release 并上传同版本 ZIP。

典型命令：

```powershell
python release\check_version.py
.\release\prepare_release.ps1 -CreateTag
git push origin vX.Y.Z
```

版本检查会验证 Python 包元数据、前端版本占位符、`CHANGELOG.md` 和可选 Git 标签，避免页面、API、包元数据和 ZIP 文件名版本不一致。工作区有未提交改动时，发布脚本要求显式传 `-AllowDirty`。

## 故障排查与限制

- **服务无法启动**：确认 Python 3.10–3.14、依赖安装成功，并使用启动日志中的实际端口。
- **`/api/detect` 返回 503**：后端 OpenCV 不可用；检查依赖，或使用浏览器检测器和人工四角校正。
- **识别方向 / 颜色错误**：先检查相邻边约定，再做四角校正、旋转网格、手动改色或重新拍摄。
- **原生 EXE / PDB 缺失**：运行 `native\build.ps1` 和 `native\build_tables.ps1`；没有 C++ 编译器时可继续用 Python 求解器。
- **`WinError 5`**：受限 Windows 不能创建 worker 时，Python 严格求解器会自动回退到单进程，结果语义不变但可能变慢。
- **三阶未证明**：检查 `/api/solve/{job_id}` 的 `status` 和 `proof_status`；超时、排队和取消都不会把候选解自动标记为最短。

项目面向单机、单用户和本地浏览器，不提供账号、TLS、远程多用户隔离或生产级队列。严格三阶证明可能需要较长时间和较大内存；真实照片效果取决于光照、反光、遮挡和拍摄方向。
