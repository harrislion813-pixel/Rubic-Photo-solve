1.11.0 发布验收记录，日期为 2026-10-05（Asia/Shanghai）。本版落实 HTM 活动层候选上界采用、Phase-1 查询及专用展开、启动缓存和原生六方向候选优化。版本、页面、Python 元数据和 Windows 说明均为 1.11.0。

**性能与范围。** 六照片状态 36 次新旧真实 HTTP 请求，30 秒原期限、15 总额度，严格最短完成数 11/18→15/18，PAR-2 平均耗时下降 38.9%，没有新增超时。initial-16 仍三次超时；六状态不代表任意打乱的时间保证。独立消融及所有慢记录见 [优化报告](htm-speed-optimization-report-2026-10-05.md)。这组性能数据在发布前冻结，并非下面的便携包功能检查重新测得的加速比。

HTM 默认原生六方向候选，一份候选额度、至多 1.5 秒总预算，与证明共享原额度；内部上界及时传送，提前页面交付仍默认关闭。QTM 保留已发布的默认策略及完整 strong/Tail 资产，HTM/QTM 距离独立。两个引擎均为 Portable x64 O3/LTO、非 PGO。HTM 独立强表本轮仅完成 [设计](htm-strong-table-design-2026-10-05.md)，没有生成或加入包。

**本地检查。** 完整 Python/原生/照片组 172 项通过；增加跨平台候选协议回归后，覆盖率组 118 项通过，两组共 182 个不同用例。共享及 HTM 分支覆盖率 73.47%，保留原 70% 门槛。新增协议回归覆盖无效度量/长度/公式、旧请求响应、回调失败、排队原期限和取消时的进程所有权；与真实原生用例互补。

| 验收 | 结果 |
| --- | --- |
| 版本、Ruff、Python 编译、C++ clang-format、Git whitespace | 通过 |
| 四组 Node 前端检查 | 通过 |
| 独立 wheel 安装 | 1.11.0，22 个 solver 文件；包括新增 native_fast 的隔离导入 |
| 精简源码包 | 80 文件，逐项等于当前源码；没有资产、缓存、EXE、环境、测试或报告 |
| 从源码包独立编译 | HTM/QTM Portable 均通过；显式 HTM/QTM 浅层检查分别为 262 / 127 状态 |
| 全新解压的真实 EXE | 接口、页面和响应头为 1.11.0；二阶/三阶 × HTM/QTM 四请求均严格完成；半转成本分别为 1 / 2，公式独立回放 |
| 包内新版候选与证明 | initial-1 / initial-12 确认 18 / 17 步最短；记录真实 adopted 事件，候选一份额度，提前交付关闭，没有 fallback/candidate_error；全部公式声明回放 |
| 安装校验 | Python 和包内 Windows PowerShell 校验器均通过，21 项运行资产 |
| 来源与旧资产 | 当前应用来源、PyInstaller 模块路径（含 native_fast）、原生构建来源全部核对；此前 17 个表/缓存散列保持一致 |
| ZIP 与真实分段合并 | 155 文件逐项完整读取、CRC 和 SHA-256 核对；实际执行 QTM.cmd 的编码合并逻辑，合并 ZIP 与构建 ZIP 相同 |

包内两照片请求分别耗时 12.890 / 13.781 秒，属于本轮功能验收单次记录，不能与旧包直接构成性能对照。源码浅层检查没有生成巨型表，运行包继续使用已有、经完整散列核对的资产。

原始记录保存在 [release-1.11.0](benchmarks/release-1.11.0/)。首次全目录 lint 被冻结评审脚本的格式触发，采用仅针对两个原始脚本的定向例外以保留证据字节。首次完整测试因 GCC 的中文临时目录出现两个编译启动错误，改用系统临时目录后 172 项全部通过；wheel 子进程显式 UTF-8 后重跑隔离安装。覆盖率首次为 69.76%，补齐真实桥接协议边界回归后达到 73.47%，没有降低门槛。首次便携包验收发现 Windows 校验器仍按 19 项计数，改为完整包 21 项、HTM 包 9 项后重新构建和全新解压；本次发布采用 `QtmStrong-v2` 和 `products-final`，早期失败日志保留。

**附件。** 完整 ZIP 为 **2,312,163,138 字节**，SHA-256 为 `631e6e19c03d61b3ad0d92bd5ee89ea7d9ffc218e023bd777c6c0ee80b43852a`。上传以下五项，每项均小于 GitHub 的单附件上限；完整 ZIP 通过两个分段合并获得。

| 附件 | 字节数 |
| --- | ---: |
| RubicPhotoSolve-1.11.0-QtmStrong-windows-x64.zip.001 | 1,610,612,736 |
| RubicPhotoSolve-1.11.0-QtmStrong-windows-x64.zip.002 | 701,550,402 |
| QTM.cmd | 4,723 |
| RubicPhotoSolve-1.11.0-source.zip | 284,982 |
| SHA256SUMS.txt | 416 |

下载两个分段与 `QTM.cmd` 到同一目录，双击合并并校验，完整解压后运行 `启动魔方求解器.cmd`。源码用户按 [README](../README.md) 在本机编译并生成表。更新时解压到新目录。

[包身份、完整 ZIP 与合并散列](benchmarks/release-1.11.0/package-identity.json)、[实际便携包 HTTP（归档）](evidence-archive-2026-10-06.md#file-c8d77d1cca2f)、[源码构建与浅层检查](benchmarks/release-1.11.0/source-build-checks.json)、[最终覆盖率](benchmarks/release-1.11.0/coverage-final.json)分别记录对应范围。基准及发布证据使用 Git `-text` 属性保留原字节。

发布顺序为提交来源与验收、推送 `v1.11.0`、上传已校验附件到草稿、确认标签 CI 和远端附件散列后再标为正式发布。[发布页](https://github.com/harrislion813-pixel/Rubic-Photo-solve/releases/tag/v1.11.0)及 [Actions](https://github.com/harrislion813-pixel/Rubic-Photo-solve/actions)为远端状态的依据。

首个提交的 [主分支 CI](https://github.com/harrislion813-pixel/Rubic-Photo-solve/actions/runs/37230116261)全部通过；[首轮标签 CI](https://github.com/harrislion813-pixel/Rubic-Photo-solve/actions/runs/37230130015)及其一次重跑在 15 线程的未证明上界测试失败。原 harness 在初始进度就发送候选，并要求在 0.6 秒内采用；该虚拟机在此期限内仍在创建线程，没有到达活动监督阶段。测试改为等待真实工作线程进度、确认候选采用后至少 0.15 秒内仍有搜索节点增加，再主动取消，检查保留的 19 步候选、16 层证书和非最优终态。超时与取消竞争用例及最优上界采用后的 0.25 秒退出检查保持原判定。5 秒仅是此同步测试的安全上限，生产请求期限和已冻结性能矩阵没有改动。

此修正仅影响验收 harness 与记录，应用、原生二进制、源码 ZIP 和五个发布附件内容未改变；尚未正式发布的标签在修正验证后更新到包含该验收修正的提交。两次初始失败的远端记录完整保留。

修正后的本地原生回归 [7 项全部通过，24.16 秒](benchmarks/release-1.11.0/incumbent-sync-regression.log)，包括上述 32 组方向/线程/停止场景及两组额外校验；[JUnit](benchmarks/release-1.11.0/incumbent-sync-regression.xml)记录通过状态。Ruff 与 Git 空白检查亦通过。
