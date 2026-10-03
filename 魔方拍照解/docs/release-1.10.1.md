# 1.10.1 发布验收记录

日期：2026-10-03（Asia/Shanghai）。本次为资源管理与诊断维护版本：保留 HTM 请求额度、取消/期限保护和 QTM 初始化暂停修复，版本号升级为 1.10.1。

HTM 提前交付默认关闭；QTM 使用 generic 展开、legacy 候选调度，late Tail 默认关闭。完整 strong/Tail 资产仍正常使用。两个引擎均为 Portable x64、普通 O3/LTO，未训练或启用 PGO。本次不宣称默认求解更快；本轮实验的单状态退化以及保守默认包曾出现的 HTM initial-1 超时，见[原实施报告](htm-qtm-next-speed-report-2026-10-03.md)。该报告的 72 请求数据属于此前冻结的 1.10.0 实验包。

## 本地验证

| 检查 | 结果 |
| --- | --- |
| Python 与共享代码分支覆盖门槛 | 108 项通过；覆盖率 72.49%，保留 70% 阈值 |
| HTM/QTM 原生、完整/损坏资产、暂停/取消、照片回归 | 57 项通过，无跳过 |
| Node 前端与原子报告写入 | 四个前端测试文件通过；两个原子写入测试通过 |
| Ruff、C++ clang-format、Python 编译、版本与 Git whitespace | 通过 |
| wheel 独立安装 | 1.10.1；21 个 solver 文件；隔离环境导入通过 |
| 六组实拍输入身份 | 36 张照片、人工参考和合法 Facelets 散列核对通过 |
| 精简源码独立解压 | 77 文件；两个 Portable 引擎独立编译成功；HTM/QTM 深度 2 的浅层检查通过，分别检查 262 / 127 状态 |
| 实际便携包 HTTP | 二阶/三阶 × HTM/QTM 四请求均严格完成，独立回放与半转成本检查通过；接口和页面版本均为 1.10.1 |
| 普通入口真实页面 | initial-1 / 12 的 QTM 成本 22 / 20 严格确认；实际采用 strong/Tail，专用展开量为 0；311 条公式声明回放无错误 |
| 桌面/手机布局 | 两组截图与自动布局检查通过；人工复核 initial-12 两种截图 |
| 包身份与全部运行资产 | 42 个应用源码、两引擎构建来源、19 个运行资产核对通过；原冻结 335 文件未改，17 个表/缓存文件与原基线相同 |
| ZIP 内容与分段合并 | 153 文件完整读取/CRC 验证；归档内 19 资产 SHA-256 与清单相符；真实 QTM.cmd 合并后的完整 ZIP 与原包相同 |

源码编译与浅层检查没有重新生成巨型 strong/Tail 表；本次沿用已存在的相同格式资产并完整核对散列，完整原生与损坏资产检查另有实际证据。页面检查是功能验收，不是重复性能采用矩阵。

原始证据见 [release-1.10.1](benchmarks/release-1.10.1/)。测试临时目录遗漏、Unicode 编译输出路径和 HTTP 检查脚本错误的最初记录分别保留；修正后才有最终通过记录。Unicode 输出路径修复只涉及验收 harness，使用相对输出路径，未降低断言或发布门槛。

## 发布附件

集成包完整 ZIP 为 **2,307,015,054 字节**，SHA-256 为 `e8cc01744e1b57be11d31ed7ce3b51578683f58de16de1c3d7689f9b6a6eb2e3`。上传 `.001`、`.002`、`QTM.cmd`、`RubicPhotoSolve-1.10.1-source.zip` 和 `SHA256SUMS.txt` 五项。精简源码 ZIP 为 **270,916 字节、77 文件**，不含运行表、缓存、环境、测试照片或性能报告。

[压缩包及合并核对](benchmarks/release-1.10.1/archive-verification.json)、[实际包身份](benchmarks/release-1.10.1/package-identity.json)、[页面公式验证](benchmarks/release-1.10.1/page-validation.json)分别记录对应范围。构建前源码身份快照记录当时的未提交状态，实际包按内容散列核对；远端提交、标签、CI 和附件状态以 GitHub 验证为准。

原性能矩阵另有[无损 gzip 归档](benchmarks/next-speed-2026-10-02/formal-final/formal-matrix.json.gz)和[散列记录](benchmarks/next-speed-2026-10-02/formal-final/formal-matrix-archive.json)，解压字节与原始记录完全相同，避免 GitHub 单文件容量限制。

本轮基准与发布证据使用 Git `-text` 属性保存原始字节，避免跨平台换行转换改变已冻结的散列。
