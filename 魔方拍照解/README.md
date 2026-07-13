# 魔方拍照解：二阶 / 三阶本地识别与最短解

这是一个运行在本机浏览器中的魔方求解器。选择二阶（2×2）或三阶（3×3），上传六个面的照片，确认识别结果后，应用会生成可执行的复原步骤，并在条件允许时继续验证 HTM 严格最短解。

当前版本以 `cube_app.__version__` 和运行时 `GET /api/version` 的返回值为准。版本、变更记录和发布方式见[版本与发布](#版本与发布)。

## 目录

- [功能概览](#功能概览)
- [快速开始](#快速开始)
- [用户操作流程](#用户操作流程)
- [拍摄与六面方向约定](#拍摄与六面方向约定)
- [识别结果如何得到](#识别结果如何得到)
- [求解结果如何解读](#求解结果如何解读)
- [项目结构](#项目结构)
- [API 接口](#api-接口)
- [原生求解器与剪枝表](#原生求解器与剪枝表)
- [开发、测试与基准](#开发测试与基准)
- [版本与发布](#版本与发布)
- [故障排查与限制](#故障排查与限制)

## 功能概览

- 本地网页界面：服务默认只监听 `127.0.0.1`，照片和识别数据不会上传到云端。
- 二阶识别与求解：没有中心块，自动从 24 个色块恢复 6 种颜色，并按 HTM 求严格最少步数。
- 三阶识别与混合求解：先返回可执行的快速解，再在后台逐深度验证更短解；验证完成后自动替换为严格结果。
- 多候选视觉检测：后端 OpenCV 检测器会返回候选四角、置信度和质量信息；浏览器检测器可作为降级路径。
- 人工校正：可旋转单面网格、拖动四角透视区域、修改非中心色块颜色。
- Windows 便携发布：发布 ZIP 自带 Python 运行环境所需的应用文件、OpenCV、C++ 求解器和基础 PDB 表，不需要另装 Python。

> “快速解”与“严格最短解”是两种不同状态。快速解可以立即执行，但在 `proof_status` 变为 `complete` 之前，不应把它称为已经证明的最短解。

## 快速开始

先选择适合你的使用方式：

| 目标 | 推荐方式 | 是否需要 Python | 是否需要 C++ 编译器 |
| --- | --- | --- | --- |
| 直接拍照并求解 | Windows 便携版 | 否 | 否 |
| 阅读或修改 Python/前端代码 | 源码运行 | 是，3.10–3.14 | 否 |
| 构建原生求解器或发布包 | 开发环境 | 是，3.10–3.14 | 构建原生核心时需要 |

### 方式 A：使用 Windows 便携版（普通用户推荐）

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

包内通常包含：

- `RubicPhotoSolve.exe`：服务入口；
- `web/`：前端页面和静态资源；
- `cube_solver.exe`：C++ 严格搜索核心（若构建时可用）；
- corner / phase-1 PDB：原生求解所需的基础剪枝表；
- `VERSION.txt`：与包文件名一致的版本号；
- `README-Windows.txt`：便携版的简明说明。

如果某个原生文件或 PDB 缺失，服务会回退到 Python 求解器；这通常影响速度，不会改变接口格式。

### 方式 B：从源码运行

所有命令都在本 README 所在的应用目录执行。

#### 第 1 步：检查 Python

```powershell
python --version
```

要求 Windows、Python 3.10–3.14。预期输出形如 `Python 3.14.4`。若命令不存在，请安装受支持版本，并在安装器中启用 “Add Python to PATH”。

#### 第 2 步：创建虚拟环境

```powershell
python -m venv .venv
```

成功后会出现 `.venv` 目录。如果 `ensurepip` 失败，可使用项目现有的可用 Python 环境继续，但不要混用多个 Python 安装。

#### 第 3 步：激活虚拟环境

```powershell
.\.venv\Scripts\Activate.ps1
```

提示符前通常会出现 `(.venv)`。若 PowerShell 执行策略阻止脚本，只对当前窗口临时放行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

#### 第 4 步：安装运行依赖

```powershell
python -m pip install -r requirements.txt
```

安装完成后检查关键依赖：

```powershell
python -c "import cv2, numpy; print(cv2.__version__, numpy.__version__)"
```

#### 第 5 步：启动服务

```powershell
python server.py
```

默认端口是 `8765`；如果被占用，服务会在 `8765`–`8794` 中寻找可用端口。始终使用终端实际打印的地址。

#### 第 6 步：验证服务

新开一个 PowerShell 窗口，根据实际端口执行：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/version
```

预期返回 `ok=True`、`version=1.3.1`。随后用浏览器打开同一地址的根路径。

#### 第 7 步：停止服务

回到运行 `python server.py` 的窗口按 `Ctrl+C`。

OpenCV 是后端照片定位所需的可选运行能力。未安装或不可导入时，应用仍能启动，但 `/api/detect` 会返回 `503`，前端只能使用浏览器内置检测器或人工四角校正。

### 方式 C：开发环境

#### 第 1 步：建立开发环境

```powershell
.\setup-dev.ps1
```

脚本会创建或复用 `.venv`，安装锁定的开发依赖，并以 editable 模式安装当前项目。

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

页面顶部选择 `2×2` 或 `3×3`。二阶和三阶的照片数量、颜色校验和求解器不同，切换类型后请重新确认已上传的图片。

### 第 3 步：按约定拍摄六面

依次拍摄 `U`、`R`、`F`、`D`、`L`、`B`。每张照片都从该面的外侧正对拍摄，并按照下方[面标签](#面标签)规定的边朝上。

### 第 4 步：上传到正确位置

按 `U R F D L B` 六个位置上传照片。每个位置代表魔方的固定面，不是照片中“看起来像”的方向。`F` 是输出解法使用的前面基准。

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

### 第 10 步：跟踪证明进度

点击求解后：

1. 二阶通常直接返回严格最短解；
2. 三阶可能先显示快速解，并显示“尚未证明最短”；
3. 页面约每秒轮询一次后台任务；
4. 后台证明完成后，结果会显示严格最短标记；
5. 任务超时或手动取消时，已有快速解不会被清空，但必须保留“未证明”状态。

### 第 11 步：执行转动

始终以已选定的 `F` 面作为前面、`U` 面作为上面执行公式。`R` 表示右面顺时针，`R'` 表示右面逆时针，`R2` 表示右面转 180°；其他字母同理。顺逆时针均以正对该面的视角判断。

## 拍摄与六面方向约定

### 照片质量建议

- 从对应面的外侧尽量正对拍摄，保证九个贴纸都可见；
- 光线均匀，避免强烈镜面反光、阴影、手指遮挡和背景中相似方形物体；
- 魔方不必填满画面，也不要求照片是正方形；
- 魔方过小时，优先靠近拍摄或使用四角校正；
- 若使用带 Logo 的中心贴纸，尽量保证中心区域没有大面积遮挡。

### 面标签

| 标签 | 含义 | 约定 |
| --- | --- | --- |
| `U` | Up，上面 | `B` 边朝上，即 `F` 边朝下 |
| `R` | Right，右面 | `U` 边朝上 |
| `F` | Front，前面 | `U` 边朝上；也是解法的前面基准 |
| `D` | Down，下面 | `F` 边朝上 |
| `L` | Left，左面 | `U` 边朝上 |
| `B` | Back，后面 | `U` 边朝上 |

如果拍摄时的相邻边没有按上表放置，上传后请旋转该面的网格。六张独立照片可能存在多个空间方向解释，应用不会在有歧义时静默猜测。

如果希望换一个前面基准，应把该面图片放入 `F`，并按真实魔方的相邻关系重新放置其余五面；不能只交换一个标签而保留其他面不变。

## 识别结果如何得到

识别分为“定位”和“颜色分配”两步：

1. 后端 OpenCV 检测器综合轮廓、边缘、网格结构和候选四角，估计魔方面区域；
2. 对四角区域做透视矫正，再按九宫格采样；
3. 采样会降低高亮、低饱和反光像素的影响。普通色块同时观察中心和边缘，中心块使用环形区域以减少 Logo 污染；
4. 三阶会结合六个中心块，把 48 个非中心色块全局分配为 6 种颜色，并要求每种颜色最终有 9 个；
5. 二阶没有中心块，会把 24 个采样色块聚成 6 组、每组 4 个，再用 8 个角块的颜色组合与朝向约束确定颜色标签；
6. 如果状态无法组成合法魔方，前端会提示重新校正方向、四角或颜色，而不是继续生成不可信解法。

OpenCV 不可用时，前端浏览器检测器仍可尝试定位；如果定位质量不足，直接使用四角校正通常更稳定。

## 求解结果如何解读

### HTM 计步

项目使用 HTM（Half Turn Metric）：`R`、`R'` 和 `R2` 各计 1 步。结果中的 `depth` 就是 HTM 步数，`solution` 是空格分隔的转动记号。

### 二阶（2×2）

- 只建模角块排列和扭转；
- 将整体旋转的 24 种空间朝向视作同一个复原状态；
- 使用角块排列 / 朝向剪枝表与逐层 IDA*；
- 只有更短深度全部搜索失败后才返回当前解；
- 最大搜索深度为 11，返回时 `proof_status` 为 `complete`。

### 三阶（3×3）

三阶采用混合流程：

```text
输入 facelets
    ├─ 短时严格探测（probe）──找到证明解──立即返回 complete
    └─ 快速求解（fast）──────返回候选解──后台 IDA*/原生核心继续证明
                                      ├─ complete：严格最短已证明
                                      ├─ timeout：当前候选可用，但未完成证明
                                      └─ cancelled / error：任务被取消或失败
```

后台搜索按深度从小到大进行，只搜索比当前候选更短的深度。超时只代表证明尚未完成，不代表候选解错误。随机极难状态的严格证明可能耗时较久，可在页面调整“最短验证超时”。

## 项目结构

```text
魔方拍照解/
├─ server.py                 # 本地 HTTP 服务、API 路由、任务队列和静态文件服务
├─ windows_launcher.py       # Windows 启动器，可选自动打开浏览器
├─ cube_app/
│  ├─ __init__.py            # 唯一版本源 __version__
│  ├─ runtime.py              # 源码 / PyInstaller 运行根目录解析
│  ├─ vision.py              # 图像解码、透视区域和九宫格采样
│  ├─ detection.py           # 候选四角检测与检测管线
│  ├─ color.py               # 颜色原型、聚类和合法状态校验
│  ├─ cubie.py               # 面贴纸与角棱块状态转换
│  ├─ fast.py                # 三阶前台快速求解
│  ├─ optimal.py             # Python 严格最短搜索与后台任务
│  ├─ native.py              # C++ 原生求解器调用和资产校验
│  ├─ two_by_two.py          # 二阶 IDA* 求解器
│  └─ tables.py              # Python 剪枝表
├─ web/
│  ├─ index.html              # 页面结构、说明和版本占位符
│  ├─ app.js                  # 上传、校正、求解和任务轮询
│  └─ styles.css              # 页面样式
├─ native/
│  ├─ src/                    # C++20 求解器实现
│  ├─ include/                # 原生头文件
│  ├─ build.ps1               # 编译 cube_solver.exe
│  └─ build_tables.ps1        # 生成 / 校验 PDB 与联合表
├─ tests/                     # Python、Node、API、视觉和原生集成测试
├─ release/
│  ├─ build_windows.ps1       # 构建版本化 Windows ZIP
│  ├─ prepare_release.ps1     # 发布前检查、测试、构建和打标签
│  └─ check_version.py        # 版本一致性检查
├─ requirements*.txt          # 运行、开发、发布依赖锁定
├─ pyproject.toml             # 包元数据、版本配置和工具配置
└─ CHANGELOG.md               # 版本变更记录
```

## API 接口

服务默认绑定 `127.0.0.1`。以下示例假设端口为 `8765`，实际端口以启动日志为准。

### `GET /api/version`

用于检查服务是否可用以及前后端版本：

```json
{"ok": true, "version": "1.3.1"}
```

### `POST /api/detect`

请求体：

```json
{"image": "data:image/jpeg;base64,...", "cube_size": 3}
```

`cube_size` 只能是 `2` 或 `3`。成功时返回 `detected`、主候选 `corners`、`confidence`、`method`、`quality`、候选列表和 `fallback_used`。没有检测器时返回 HTTP `503`；请求或图片无效时通常返回 `400`。

### `POST /api/solve`

请求体至少包含面贴纸字符串：

```json
{
  "facelets": "...",
  "cube_size": 3,
  "max_depth": 20,
  "timeout_seconds": 180
}
```

`facelets` 只允许使用 `U R F D L B` 六个字符，并按六个面的顺序拼接：`U`、`R`、`F`、`D`、`L`、`B`。三阶每面 9 个字符，共 54 个；二阶每面 4 个字符，共 24 个。三阶还要求六个中心位置分别是对应面标签，且每种字符数量必须正确。

参数范围：`cube_size` 为 `2` 或 `3`；`max_depth` 为 `0`–`20`（二阶内部最多使用 11）；`timeout_seconds` 为 `0.1`–`3600`，传 `0`、`null` 或 `"none"` 表示不设置超时。

- 二阶通常同步返回 `moves`、`solution`、`depth`、`metric`、`optimal` 和 `proof_status: "complete"`；
- 三阶可能同步返回快速结果，也可能返回 `job_id` 与 `proof_status: "queued"`；
- 贴纸字符串不合法、参数错误或搜索容量已满时分别返回 `400` 或 `503`。

### `GET /api/solve/{job_id}`

查询后台任务。返回 `status`、进度字段和（完成时）最终结果；排队任务还会返回 `queue_position`。任务不存在返回 `404`。

### `POST /api/solve/{job_id}/cancel`

请求取消后台搜索。成功返回任务 ID 和当前状态；已经完成、超时或失败的任务不会重新启动。

## 原生求解器与剪枝表

原生核心使用 C++20。只有需要从源码构建原生加速时才需要 MSYS2 UCRT64 或其他可用的 `g++`；脚本会依次尝试 `-Compiler` 参数、`CXX` 环境变量和 `PATH`。

```powershell
.\native\build.ps1
.\native\build_tables.ps1
```

默认资产写入 `.cache/native/`，包括对称联合表、角块表和深度 6 反向表。表文件以只读内存映射加载，并带数据校验；缺失或损坏时服务会回退到 Python 实现。

CI 的最小原生资产：

```powershell
.\native\build_tables.ps1 -CiMinimal
```

实验性完整六棱块模式库会显著增加磁盘和内存占用，默认不加载：

```powershell
.\native\build_tables.ps1 -IncludeEdgePdbs
$env:CUBE_NATIVE_EDGE_PDBS = "1"
python server.py
```

如需生成调试符号，可按脚本参数选择 `-IncludeEdgePdbs`；发布构建默认携带基础 PDB，便于定位原生崩溃。

## 开发、测试与基准

### 一键检查

```powershell
.\tests\check.ps1
```

该脚本会检查工具链和版本配置，运行前端 Node 测试、Ruff、Python 测试、覆盖率门禁和 `compileall`。测试临时文件放在 `.cache/test-tmp`，避免污染系统临时目录。

### 分项检查

```powershell
node tests\recognition.test.js
node tests\color.test.js
node tests\two_by_two_color.test.js
node tests\solver_ui.test.js
python -m pytest -ra
python -m compileall cube_app server.py windows_launcher.py
python release\check_version.py --tag v1.3.1
```

CI 对 `cube_app` 和 `server.py` 执行至少 70% 的分支覆盖率门禁；依赖本地 EXE/PDB 或实拍图片的测试会在缺少资源时跳过。当前仓库未必包含 `tests/initial/` 实拍素材，因此看到 real-image 用例被跳过是预期行为。

CI 中常见的 `SKIPPED` 不等于失败：

- Linux Python 矩阵没有编译 Windows 原生求解器，因此 `test_native_solver.py` 的原生二进制用例会跳过；同一套原生能力在独立的 `Native solver (Windows / UCRT64)` 作业中构建和测试。
- 仓库没有提交完整实拍图片时，`test_real_images.py` 会跳过；提供 `tests/initial/U1.jpg` 到 `B1.jpg` 的完整一组图片后才会执行。
- 判断 CI 是否失败应看最后的 `FAILED`、`ERROR` 和进程退出码，不要把 `SKIPPED` 行本身当作错误。

本地复现 CI 的 Python 覆盖率门禁：

```powershell
.\.venv\Scripts\python.exe -m pytest -ra `
  -m "not native_binary and not native_pdb and not native_slow and not vision_real" `
  --cov=cube_app --cov=server --cov-branch `
  --cov-report=term-missing --cov-fail-under=70
```

### 视觉回归与标注

复制 `tests/vision_annotations.example.json` 为本地标注文件，填写归一化四角坐标后运行：

```powershell
python tests\benchmark_vision.py tests\vision_annotations.json
```

报告包含漏检、负样本误检、角点误差、关键失败率、延迟和按场景统计的失败数。实拍颜色回归按文件名组号读取：

```text
tests/initial/U1.jpg  R1.jpg  F1.jpg  D1.jpg  L1.jpg  B1.jpg
tests/initial/U2.jpg  R2.jpg  F2.jpg  D2.jpg  L2.jpg  B2.jpg
```

```powershell
python tests\extract_real_patches.py --group 1 | node tests\real_color.test.js --group 1
python tests\extract_real_patches.py --group 2 | node tests\real_color.test.js --group 2
```

### 求解性能

```powershell
python tests\benchmark_solver.py --timeout 30
```

C++ 格式检查使用项目根目录的 `.clang-format`：

```powershell
$files = Get-ChildItem native\src, native\include -Recurse -File -Include *.cpp, *.hpp
clang-format --dry-run --Werror --style=file $files.FullName
```

## 版本与发布

版本只在 `cube_app/__init__.py` 中维护：

```python
__version__ = "X.Y.Z"
```

发布使用语义化版本 `MAJOR.MINOR.PATCH`。修复兼容性或 CI 问题增加 `PATCH`；向后兼容的新功能增加 `MINOR`；不兼容变更增加 `MAJOR`。

### 第 1 步：确定新版本号

检查当前版本和现有标签：

```powershell
python -c "from cube_app import __version__; print(__version__)"
git tag --list "v*" --sort=-version:refname
```

不要移动或复用已经推送到远程的标签。若 `v1.3.0` 已存在，而后续需要修复 CI，应发布 `v1.3.1`。

### 第 2 步：更新唯一版本源

编辑 `cube_app/__init__.py`：

```python
__version__ = "1.3.1"
```

不要在 `pyproject.toml` 再写静态版本；它会从 `cube_app.__version__` 动态读取。

### 第 3 步：更新变更记录和文档示例

在 `CHANGELOG.md` 的 `[Unreleased]` 下方增加对应版本、日期以及 `Added`、`Changed` 或 `Fixed` 条目。README、API 示例和命令中若显示旧版本，也要同步更新。

### 第 4 步：刷新 editable 包元数据

修改版本后，本地 `.venv` 中的包元数据可能仍显示旧版本。执行：

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

### 第 5 步：检查版本一致性

```powershell
.\.venv\Scripts\python.exe release\check_version.py --tag v1.3.1
```

脚本会检查语义化版本、Python 包配置、前端版本占位符、`CHANGELOG.md` 和标签名称。预期只输出 `1.3.1`。

### 第 6 步：运行完整检查

```powershell
.\tests\check.ps1
```

任何 `FAILED` 或非零退出码都必须先修复。预期的原生/实拍 `SKIPPED` 可按上一节解释处理。

### 第 7 步：审查并提交改动

```powershell
git status --short
git diff --check
git diff
git add -- ..\README.md README.md CHANGELOG.md cube_app\__init__.py tests\test_runtime.py tests\test_two_by_two.py
git diff --cached
git commit -m "Fix Linux CI and release v1.3.1"
```

这些路径对应当前 `v1.3.1` 修复。以后发布时应按 `git status` 的实际改动调整文件列表。提交前必须检查 `git diff --cached`，确保本次文件全部纳入且无关文件没有混入。

### 第 8 步：确认工作区干净

```powershell
git status --short
```

预期没有输出。`prepare_release.ps1 -CreateTag` 故意拒绝脏工作区，避免标签指向未包含本地修改的提交。

### 第 9 步：构建发布包并创建本地标签

```powershell
.\release\prepare_release.ps1 -CreateTag
```

脚本依次执行版本检查、完整测试、Windows 便携包构建、SHA256 计算和本地 `vX.Y.Z` 标签创建。任何步骤失败都不会创建成功标签。

只想临时检查脚本时可以使用 `-SkipTests -SkipBuild -AllowDirty`；`-AllowDirty` 不能与 `-CreateTag` 同时使用，也不能作为正式发布方式。

### 第 10 步：确认产物和标签

```powershell
Get-Item .\dist\RubicPhotoSolve-1.3.1-windows-x64.zip
Get-FileHash .\dist\RubicPhotoSolve-1.3.1-windows-x64.zip -Algorithm SHA256
git show --no-patch v1.3.1
```

### 第 11 步：推送提交和标签

```powershell
git push origin main
git push origin v1.3.1
```

只有推送 `v*` 标签才会触发 GitHub Release 发布任务。只推送 `main` 不会创建 Release。

### 第 12 步：检查 GitHub Actions 和 Release

1. 打开仓库的 Actions 页面；
2. 找到分支为 `v1.3.1` 的 CI 运行；
3. 等待 Version、Lint、Python、Frontend 和 Native Windows 全部通过；
4. `Publish GitHub Release` 随后下载经过测试的 Artifact；
5. 在 Releases 页面确认标题、标签和 ZIP 文件名一致。

如果标签已推送但没有 Release，先检查 Actions 中是否存在失败任务；发布任务依赖所有前置任务成功，不会在测试失败时上传未经验证的包。

## 故障排查与限制

### PowerShell 提示“禁止运行脚本”

只对当前 PowerShell 窗口临时放行，然后重试原命令：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

不需要永久修改整台计算机的执行策略。

### 提示 `No module named pytest`

说明当前使用的不是项目开发虚拟环境，或开发依赖尚未安装：

```powershell
.\setup-dev.ps1
.\.venv\Scripts\python.exe -m pytest --version
```

### 服务无法启动或端口不同

- 确认使用的是 Python 3.10–3.14；
- 运行 `python -m pip install -r requirements.txt`；
- 端口 `8765` 被占用时，使用启动日志中打印的备用端口；
- Windows 便携版请保持命令行窗口运行，关闭窗口会停止服务。

### `/api/detect` 返回 503

这是后端 OpenCV 检测器不可用的信号。确认依赖安装成功；临时使用浏览器检测器或手动四角校正不影响服务启动。

### 识别颜色或方向不正确

先按[六面方向约定](#拍摄与六面方向约定)重新检查相邻边，再依次尝试：四角校正、旋转网格、手动修改非中心色块、重新拍摄。不要只修改颜色而忽略面之间的方向关系。

### 原生程序或 PDB 缺失

源码环境执行 `native\build.ps1` 和 `native\build_tables.ps1`；没有 C++ 编译器时可以继续使用 Python 求解器。便携版应从完整 ZIP 解压，不能只复制单个 EXE。

### 出现 `WinError 5` 或并行搜索无法创建进程

这是受限 Windows 环境中创建 worker 进程失败的常见情况。当前 Python 严格求解器会捕获该错误并回退到单进程搜索；结果语义保持不变，但速度可能下降。

### 三阶一直显示“未证明最短”

这通常表示搜索仍在运行、超时或排队，不等于快速解不可执行。查看 `GET /api/solve/{job_id}` 的 `status` 和 `proof_status`；提高超时时间、准备原生 PDB 或取消后重新提交都可以改变运行时间，但不能把未完成证明手动标成最短。

### 发布脚本提示工作区不干净

先查看真正的改动：

```powershell
git status --short
git diff
```

需要发布的改动应先提交；不需要的改动要明确处理。不要为了绕过保护而在正式打标签时使用 `-AllowDirty`。若 `git status` 显示修改但 `git diff` 为空，可能只是 Windows 换行或索引状态问题，可先执行 `git add -- <文件>` 让 Git 重新归一化，再确认没有 staged diff。

### 标签已推送但 GitHub 没有新 Release

按顺序检查：

1. `git tag --list v1.3.1` 能看到本地标签；
2. `git ls-remote --tags origin refs/tags/v1.3.1` 能看到远程标签；
3. GitHub Actions 中存在 `headBranch=v1.3.1` 的运行；
4. 所有 Python、前端和 Windows Native 作业成功；
5. `Publish GitHub Release` 没有因前置失败而跳过。

本地创建标签不会自动上传，必须执行 `git push origin v1.3.1`。

### CI 显示很多 `SKIPPED`

`SKIPPED` 是测试根据环境主动跳过，不会单独导致失败。原生求解器在 Linux Python 矩阵中跳过、实拍图片缺失时跳过，都是设计行为。继续向日志末尾查找 `FAILED` 或 `ERROR` 才能确定真正根因。

### 项目边界

- 当前服务面向单机、本地浏览器和单用户操作，不提供账号、TLS、远程多用户隔离或生产级队列；
- 严格三阶最短证明可能需要较长时间和较大内存；
- 真实照片识别效果取决于光照、反光、遮挡和拍摄方向，建议用冻结标注集做调参；
- 仓库中的示例测试不等同于对任意手机、相机和贴纸材质的准确率保证。
