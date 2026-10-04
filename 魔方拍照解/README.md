# Cube Lens · 魔方拍照求解

在本机浏览器上传二阶或三阶魔方的六面照片，校正识别结果，再按公式复原。照片在本机处理，服务只监听 `127.0.0.1`。

**当前版本：1.11.0。HTM 和 QTM 均为正式功能。** HTM 默认把 180° 算作一步；QTM 把 180° 算作两步。QTM 正式支持二阶和三阶，三阶先返回可执行候选，再验证严格最短性。1.11.0 优化 HTM 原生候选质量、证明热路径与启动缓存，困难状态仍可能需要增加验证超时。

## 1. 选择下载

打开 [1.11.0 发布页](https://github.com/harrislion813-pixel/Rubic-Photo-solve/releases/tag/v1.11.0)。

| 用途 | 下载文件 | 还需要做什么 |
| --- | --- | --- |
| Windows 直接使用（推荐） | `RubicPhotoSolve-1.11.0-QtmStrong-windows-x64.zip.001`、`.002` 和 `QTM.cmd`，三项都下载 | 合并、解压、双击启动；已集成 HTM、QTM、Python、OpenCV 和全部运行表 |
| 本地运行或修改源码 | `RubicPhotoSolve-1.11.0-source.zip` | 安装环境，然后按第 3 节在本机编译和生成表；无需下载便携包或表文件 |
| 下载校验 | `SHA256SUMS.txt` | 可选：对照文件的 SHA-256 |

源码 ZIP 只包含应用代码、网页、C++ 源码、依赖清单、生成/校验工具与用户文档，**不包含预生成表、缓存、EXE、Python 环境、测试照片或性能报告**。GitHub 自动提供的 “Source code” 同样排除测试与报告；其应用代码在 `魔方拍照解` 子目录中。

## 2. Windows 便携包：解压即用

适用 Windows 10/11 x64，无需安装 Python、编译器或 Node.js。便携包已集成完整 HTM 与正式 QTM，网页直接选择计步方式。

1. 新建一个下载目录，例如 `D:\CubeLens下载`。
2. 将 `.001`、`.002` 和 `QTM.cmd` 放入该目录，保持原文件名。
3. 双击 `QTM.cmd`。它先校验两个分段，再合并并校验完整 ZIP。看到 `ZIP verified` 表示成功；若报错，按提示重新下载缺失或损坏的分段。
4. 解压生成的 `RubicPhotoSolve-1.11.0-QtmStrong-windows-x64.zip`，进入 `RubicPhotoSolve` 文件夹。不要在压缩包预览中运行。
5. 双击 `启动魔方求解器.cmd`，保持启动窗口打开。浏览器自动打开；否则手动访问窗口打印的地址，通常是 `http://127.0.0.1:8765/`。
6. 网页选择 `2×2` 或 `3×3`，选择 HTM 或 QTM，按第 4 节上传照片并求解。
7. 用完在启动窗口按 `Ctrl+C`。更新版本时解压到新目录。

下载、合并与解压建议预留 **12 GiB** 磁盘空间。QTM 完整强配置在参考机上的工作集约 **3.8 GiB**，还需为系统和浏览器留出内存；内存不足时会采用较小配置。

普通启动先给候选，在后台完整校验强表，再采用可用强表继续证明。需要从搜索开始就使用强表时，先关闭旧服务，再双击 `启动QTM完整强表.cmd`。加载和校验时间计入验证超时，可以在高级设置中增加超时。QTM 请求结束后短暂复用进程，闲置约 20 秒释放；HTM 请求优先。

双击 `校验安装.cmd` 可核对包内全部运行资产。请保留整个目录，尤其是 `_internal/`、`web/`、`native/`、`assets/` 和 `.cache/`。

## 3. 源码：从基本代码在本地生成完整运行表

下面以 **Windows x64、Python 3.12、PowerShell 7、MSYS2 UCRT64 GCC** 为例。支持 Python 3.10–3.14。所有生成物保存在解压后的应用目录，不需要额外下载预生成表。

完整强表生成比日常求解需要更多资源。建议 **16 GiB 或以上内存、至少 20 GiB 可用磁盘**；同时关闭占内存的程序。强表构建估算约需 4.6 GiB 内存，并要求其不超过当前可用物理内存的 70%；`-MemoryLimitGiB` 只是上限，不能让实际所需内存变少。耗时取决于电脑，可能持续数小时，不能以几分钟无新输出判断卡住。

### 步骤 1：安装三个工具（只需一次）

1. 从 [Python Windows 官方下载页](https://www.python.org/downloads/windows/)安装 Python 3.12 的 64 位版本，安装时勾选添加 Python 到 PATH。安装后重新打开终端。
2. 按 [微软 PowerShell 安装说明](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows)安装 PowerShell 7。开始菜单打开 **PowerShell 7**；后面所有 PowerShell 命令都在这个窗口中执行。原生编译脚本需要 PowerShell 7，系统自带 Windows PowerShell 5.1 不适用于这一步。
3. 从 [MSYS2 官网](https://www.msys2.org/)安装 x64 版本，建议保留默认目录 `C:\msys64`。
4. 打开开始菜单中的 **MSYS2 UCRT64**，在这个窗口执行：

```bash
pacman -S --needed mingw-w64-ucrt-x86_64-gcc
```

出现 `[Y/n]` 时按回车确认，等待安装完成。随后关闭 MSYS2 窗口，回到 PowerShell 7。后面的命令不要粘贴到 MSYS2 中。

### 步骤 2：解压源码并进入正确目录

解压 `source.zip`，打开解压后的 `RubicPhotoSolve-1.11.0-source` 目录。以下示例假定它在 `D:\CubeLens` 中，请替换为你的实际位置，保留路径两侧的引号：

```powershell
Set-Location "D:\CubeLens\RubicPhotoSolve-1.11.0-source"
Get-Item .\server.py
$PSVersionTable.PSVersion
python --version
& "C:\msys64\ucrt64\bin\g++.exe" --version
Set-ExecutionPolicy -Scope Process Bypass
```

应能看到 `server.py`、PowerShell 主版本至少 7、Python 3.10–3.14 和 GCC 版本。任一命令报错，先处理环境再继续。通过 Git 或 GitHub 自动源码包下载时，进入仓库下的 `魔方拍照解` 文件夹再执行。

### 步骤 3：建立 Python 环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

后续始终用 `.\.venv\Scripts\python.exe`，不需要激活虚拟环境。依赖安装结束且没有错误后继续。

### 步骤 4：编译两个原生引擎

逐条执行，每条完成后再执行下一条：

```powershell
.\native\htm\build.ps1 -Portable -Compiler "C:\msys64\ucrt64\bin\g++.exe"
.\native\qtm\build.ps1 -Portable -Compiler "C:\msys64\ucrt64\bin\g++.exe"
```

成功后分别生成 `native\htm\build\cube_solver_htm.exe` 和 `native\qtm\build\cube_solver_qtm.exe`，旁边各有 `build-info.json`。`-Portable` 使用通用 x64 指令，后面的资产校验也要求这种构建。MSYS2 安装在其他位置时替换 `-Compiler` 路径。

### 步骤 5：生成 HTM 主表和 Tail-6

```powershell
.\native\htm\build_tables.ps1
```

在 `assets\htm\v1` 生成以下文件，总计约 309 MiB：

- `corner_htm_v2.pdb`
- `phase1_sym_htm_v2.pdb`
- `tail_depth6_v4.pdb`

不要添加 `-CiMinimal`，它会省略完整运行所需的 Tail-6。生成时保持窗口打开，不要同时启动求解服务。

### 步骤 6：生成 QTM 全部强配置表

```powershell
.\native\qtm\build_tables.ps1 -Profile Strong -Parallelism 8 -MemoryLimitGiB 12
```

脚本依次生成 QTM 独立的辅助表、完整 Corner/Phase-1 主表、strong 强表及 Tail-8，并将 strong 转换为无损 nibble 格式。最终运行文件在 `assets\qtm\v1`，总计约 3.72 GiB：

| 文件 | 用途 |
| --- | --- |
| `corner_qtm_v3.pdb`、`phase1_qtm_v3.pdb` | QTM 完整基础下界表 |
| `strong_qtm_v4_nibble.pdb` | QTM 完整强表，约 1.64 GiB |
| `tail_qtm_depth8_v5.pdb` | QTM Tail-8，约 1.56 GiB |
| `corner_htm_v2.pdb`、`phase1_sym_htm_v2.pdb`、`tail_depth6_v4.pdb` | QTM 私有回退辅助表 |

构建会额外产生 `strong_qtm_v3.pdb` 和可能的 `.checkpoint`；这些是生成/续建文件，不进入便携发布包。Strong 配置直接生成 Tail-8，不额外生成 Tail-7。

**中断后**：重新执行相同命令，默认 `-Resume` 使用 strong 的已完成层检查点；其他已经生成的表会保留。不要手动删除 checkpoint。若提示内存不足，关闭其他应用或换用内存更大的电脑。只调整线程数不能消除强表的基础内存需求。

若仅需基础 QTM，可先执行 `.\native\qtm\build_tables.ps1 -Profile Standard -Parallelism 8`；它不生成 strong/Tail-8，三阶仍可求解，但证明可能更慢，也不能通过下面的 `QtmStrong` 完整资产校验。要获得与便携包相同的配置，请完成 Strong 步骤。

### 步骤 7：生成所有小表和坐标缓存

```powershell
.\.venv\Scripts\python.exe release\prepare_runtime_caches.py --profile QtmStrong
```

这一命令生成并检查两个引擎各自的 Python 回退表、二阶准确距离表、原生坐标缓存，以及 HTM 对称映射/Phase-2 缓存和 QTM 小型剪枝表。在 `.cache\htm` 应有 5 个运行文件，在 `.cache\qtm` 应有 4 个。第一次可能等待较久；再次执行会读取已有有效缓存。

### 步骤 8：建立清单并校验

```powershell
.\.venv\Scripts\python.exe release\verify_assets.py --root . --profile QtmStrong --write asset-manifest.json
.\.venv\Scripts\python.exe release\verify_installation.py .
```

第一个命令检查原生构建、表头的计步方式/完整标记，并记录每个运行资产的 SHA-256；第二个命令核对全部文件。看到 **`verified: 1.11.0 / QtmStrong / 21 assets`** 表示完整安装校验通过。此后改动或丢失文件，可再运行第二个命令检查；不要通过重写清单掩盖文件损坏。

### 步骤 9：启动并使用

```powershell
.\.venv\Scripts\python.exe server.py
```

浏览器打开终端打印的地址，在网页选择 HTM 或 QTM。端口被占用时程序会在 `8765`–`8784` 中寻找可用端口。

可选：关闭旧服务后，在同一窗口设置下面三项，再启动，QTM 将先完整校验强表再搜索：

```powershell
$env:CUBE_QTM_ASSET_PROFILE = "strong"
$env:CUBE_QTM_STRONG_FORMAT = "nibble"
$env:CUBE_NATIVE_ASSET_LOADING = "eager"
.\.venv\Scripts\python.exe server.py
```

普通启动适合尽早看到候选。源码与便携包使用相同的引擎和表格式；生成后的 `assets/`、`.cache/`、`native/*/build/` 都应保留，日常启动无需重新生成。

## 4. 拍照与求解

1. 选择 `2×2` 或 `3×3`，固定 `F` 为前面、`U` 为上面。
2. 拍摄并上传 `U R F D L B` 六面，尽量正对色块，避免反光、阴影与遮挡。
3. 检查四角框和网格：拖动四角修正定位，旋转网格修正方向，点击色块修正颜色。
4. 校验通过后，选择 HTM 或 QTM 并点击“开始求解”。
5. 按公式转动，保持 `F` 在前、`U` 在上。

| 拍摄面 | 画面上方对应的相邻面 |
| --- | --- |
| U（上） | B（后） |
| R（右）、F（前）、L（左）、B（后） | U（上） |
| D（下） | F（前） |

照片朝向不符时旋转该面的网格；只修改颜色不能修正方向关系。`R` 是正对右面时顺时针转 90°，`R'` 是逆时针 90°，`R2` 是 180°，其他面同理。

| 计步方式 | 90° | 180° |
| --- | ---: | ---: |
| HTM（默认） | 1 步 | 1 步 |
| QTM | 1 步 | 2 步 |

二阶使用准确距离表。三阶的“候选解”可以执行，只有页面显示 **“严格最短已确认”** 才表示最短性已经证明。超时、取消、预算不足都不表示证明完成。QTM 正式功能不意味着每个状态都能在固定时间内证明，也不保证比 HTM 快。切换模式后需重新求解，照片和人工校正保留。

## 5. 常见问题

- **脚本提示找不到编译器**：确认已在 MSYS2 UCRT64 安装 GCC，并检查 `-Compiler` 的实际路径。
- **编译报 `GetRelativePath` 不存在**：打开 PowerShell 7 后重试，检查 `$PSVersionTable.PSVersion`。
- **PowerShell 阻止脚本**：在当前窗口执行 `Set-ExecutionPolicy -Scope Process Bypass`，只对当前窗口生效。
- **QTM 不可用**：源码先完成 QTM 编译与基础表生成；完整性能再完成 Strong、小表和校验步骤。便携用户检查是否完整合并、解压全部分段。
- **生成表中断**：先关闭求解服务，再执行同一条生成命令；strong 默认从检查点续建。文件损坏时移走报错文件再重新生成，并重新校验。
- **三阶证明较久**：候选仍可使用；需要严格最短结果时增加高级设置中的验证超时，并查看已证下界和候选成本。
- **识别错位**：先调整四角，再核对六面朝向，最后修改颜色或重拍。
- **浏览器没有自动打开**：访问启动窗口显示的本机地址，保持窗口运行。
- **下载校验**：在下载目录运行 `Get-FileHash .\文件名 -Algorithm SHA256`，与 `SHA256SUMS.txt` 中的值比较。

版本可在页面或 `/api/version` 查看；历史变化见 [CHANGELOG.md](CHANGELOG.md)。
