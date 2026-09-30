# Cube Lens · 魔方拍照求解

在本机浏览器上传二阶或三阶魔方的六面照片，校正识别结果，再按公式复原。照片在本机处理，服务只监听 `127.0.0.1`。

**当前发布：1.9.0。普通用户选 HtmFull；需要 QTM 才选 QtmStrong。** 两包使用相同的完整 HTM 引擎。QTM 是实验功能，整体证明提速目标尚未达成，不能保证比 HTM 快。

## 下载哪个文件

在 [1.9.0 下载页](https://github.com/harrislion813-pixel/Rubic-Photo-solve/releases/tag/v1.9.0)选择：

| 文件 | 适合谁 | 内含加速能力 |
| --- | --- | --- |
| `RubicPhotoSolve-1.9.0-HtmFull-windows-x64.zip` | 推荐：直接使用、追求稳定 HTM 性能 | 通用 x64 原生引擎、完整 HTM 主表和 Tail-6、预生成缓存 |
| `RubicPhotoSolve-1.9.0-QtmStrong-windows-x64.zip.001`、`.002` 和 `合并QTM便携包.cmd` | 需要 QTM 的用户 | 上述全部 HTM 能力，加独立 QTM 引擎、完整 QTM 主表、无损压缩强表和 Tail-8 |
| `RubicPhotoSolve-1.9.0-source.zip` | 从 Python 源码运行或修改程序 | 应用源码、运行依赖清单、原生源码和用户辅助脚本；加速资产按下文导入 |
| `SHA256SUMS.txt` | 校验下载完整性 | 发布文件的 SHA-256 |

QTM 包较大，采用两段下载。把两个分段和合并脚本放在同一目录，双击 `合并QTM便携包.cmd`，成功后得到完整 ZIP，再解压。请保留原分段直到合并完成。建议为下载、合并与解压预留 **12 GiB** 可用磁盘空间；QTM 强配置实测工作集约 **3.8 GiB**，还需给系统和浏览器留出内存，内存不足时会降低配置或回退。

GitHub 自动提供的 “Source code” 是仓库快照；普通源码用户优先下载这里的 `source.zip`，其中已排除测试、性能报告、开发环境和发布构建目录。

## 便携包：解压即用完整加速

需要 Windows x64，无需安装 Python、编译器或 Node.js。

1. 将完整 ZIP 解压到可写目录，不能在压缩包预览中运行。
2. 双击 `启动魔方求解器.cmd`。它自动使用包内完整 HTM 原生引擎，无需设置性能开关。
3. 浏览器会自动打开；否则访问启动窗口打印的地址，通常为 `http://127.0.0.1:8765/`。
4. 保持启动窗口打开，结束时按 `Ctrl+C`。

**QTM 用户若要让本次搜索从一开始就使用完整强表，请关闭旧服务，再双击 `启动QTM完整强表.cmd`。** 在网页中选择 QTM 后开始求解。这个入口先完成强表与 Tail 校验再搜索，首次请求可能多等待数秒；等待也计入最短验证超时，可在高级设置中适当增加。

普通启动入口使用分阶段加载：先交付候选、再加载大表；长搜索层可能来不及采用刚加载的强表。因此“包内有强表”不等于每个请求都已用到强表。完整强表入口使用 eager 加载解决这个配置问题，但不承诺每个状态都更快。QTM 请求结束后可短暂复用进程，闲置约 20 秒释放；HTM 请求优先。

保留整个 `RubicPhotoSolve` 目录，尤其是 `_internal/`、`web/`、`native/`、`assets/`、`.cache/`。不要单独复制 EXE，也不要混入旧版的表。更新时解压到新目录。

## 源码：获得与便携包相同的完整加速

需要 Windows x64 和 Python 3.10–3.14。解压 `source.zip`，在包含 `server.py` 的目录打开 PowerShell；若通过 Git 下载仓库，先进入 `魔方拍照解` 目录。

### 1. 安装运行环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 导入同版本便携包的引擎和全部运行表（推荐）

同时下载并解压上面的 **1.9.0** 便携包。HTM 选 HtmFull，HTM 和 QTM 都要用则选 QtmStrong。将下例路径替换为解压后包含 `RubicPhotoSolve.exe` 的目录：

```powershell
.\.venv\Scripts\python.exe release\import_runtime.py "D:\魔方便携版\RubicPhotoSolve"
.\.venv\Scripts\python.exe release\verify_installation.py .
```

导入脚本检查版本、配置和全部资产散列后，复制原生 EXE、主表、Tail 与独立缓存；不会导入便携包的 Python 环境。看到 `verified` 和对应配置名称表示完整资产验证通过。**仅安装 Python 依赖或仅编译 EXE，不能获得完整表配置的性能。**

### 3. 启动

HTM：

```powershell
.\.venv\Scripts\python.exe server.py
```

QTM 从第一次请求就启用完整强表，与便携包的完整强表入口一致：

```powershell
$env:CUBE_QTM_ASSET_PROFILE = "strong"
$env:CUBE_QTM_STRONG_FORMAT = "nibble"
$env:CUBE_NATIVE_ASSET_LOADING = "eager"
.\.venv\Scripts\python.exe server.py
```

浏览器打开终端显示的地址。端口被占用时会在 `8765`–`8784` 中寻找可用端口。直接运行源码而未导入原生资产时，HTM 使用较慢的 Python 回退；QTM 入口需要完整安装的独立组件。

### 可选：自己编译与生成表

源码包也提供 C++20 源码。安装支持 C++20 的 `g++` 后，在应用目录执行：

```powershell
.\native\htm\build.ps1
.\native\htm\build_tables.ps1
```

不传 `-CiMinimal`，才能包含 Tail-6。默认构建按当前 CPU 优化，只在本机使用；要移到其他电脑，增加 `-Portable`。自行生成 QTM 强配置还需：

```powershell
.\native\qtm\build.ps1
.\native\qtm\build_tables.ps1 -Profile Strong
```

大表生成占用较多时间、内存与磁盘，通常直接导入便携资产更省事。本机编译不保证比已发布的通用 x64 构建快；实验参数与扩大表不作为默认使用要求。

## 拍照与求解

1. 选择 `2×2` 或 `3×3`，固定 `F` 为前面、`U` 为上面。
2. 拍摄并上传 `U R F D L B` 六面，尽量正对色块，避免反光、阴影与遮挡。
3. 检查四角框和网格：拖动四角修正定位，旋转网格修正方向，点击色块修正颜色。
4. 校验通过后，选择计步方式并点击“开始求解”。QtmStrong 包才显示 QTM 实验入口。
5. 按公式转动，保持 `F` 在前、`U` 在上。

| 拍摄面 | 画面上方对应的相邻面 |
| --- | --- |
| U（上） | B（后） |
| R（右）、F（前）、L（左）、B（后） | U（上） |
| D（下） | F（前） |

照片朝向不符时旋转该面的网格；只修改颜色不能修正方向关系。

`R` 是从正对右面的视角顺时针转 90°，`R'` 是逆时针 90°，`R2` 是 180°。其他面同理。

| 模式 | 90° | 180° |
| --- | ---: | ---: |
| HTM（默认） | 1 步 | 1 步 |
| QTM（实验） | 1 步 | 2 步 |

二阶使用准确距离表。三阶的“候选解”可以执行，只有页面显示 **“严格最短已确认”** 才是已经证明的最短解。超时、取消、预算不足都不表示最短证明完成。切换模式后需重新求解，照片和人工校正保留。

## 常见问题

- **想确认完整资产是否齐全**：源码按上面的验证命令检查；便携包可双击 `校验安装.cmd`，它会检查清单中的所有资产散列。
- **三阶证明很久未完成**：看清候选与证明状态；增加高级设置中的验证超时。完整配置也不能保证所有状态在有限时间内证明最短。
- **QTM 强表模式首次等待较长**：加载和完整校验需要时间，属于正常初始化；HTM 不会预加载 QTM 大表。
- **QTM 不可用**：HtmFull 只提供 HTM；使用 QtmStrong 或重新导入其完整资产。不要混用 1.7.x 的共享引擎与 1.9.0 的隔离目录。
- **识别错位**：先调整四角，再核对六面朝向，最后修改颜色或重拍。
- **浏览器没有自动打开**：手动访问启动窗口显示的本机地址，并保持该窗口运行。
- **PowerShell 阻止脚本**：在当前窗口执行 `Set-ExecutionPolicy -Scope Process Bypass` 后重试。
- **下载校验**：`Get-FileHash .\文件名 -Algorithm SHA256`，与 `SHA256SUMS.txt` 中的值比较。

版本可在页面或 `/api/version` 查看；历史变化见 [CHANGELOG.md](CHANGELOG.md)。
