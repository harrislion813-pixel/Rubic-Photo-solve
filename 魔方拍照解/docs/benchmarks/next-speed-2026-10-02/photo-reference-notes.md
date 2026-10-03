六组照片人工参考 · 2026-10-02

固定状态顺序为 initial-1、12、2、5、8、16；每组均为六张原始三阶照片，按 URFDLB 面顺序、照片左上开始逐行读取 9 个色块。所有面保持原照片朝向，不旋转、不镜像。原照片尺寸、前端缩放尺寸、原始文件字节数与 SHA-256，以及 ASCII Facelets 的 SHA-256 均写入 `tests/initial_solver_cases.json`。新增四组最短成本未知，不填写推测值。

`manual-photo-reference.json` 是分类器运行前冻结的人工标注来源。1、12 保留原 Facelets；2、5 对照 `tests/real_color.test.js` 历史标注逐块视觉复核，54 个色块均一致。8、16 首次从无分类标签的原照片概览和透视网格独立逐块读色，再转换为六中心对应的面符号；不是从分类器输出复制真值。白/红/绿/黄/橙/蓝分别对应 U/R/F/D/L/B。

| 状态 | 人工参考六面（每面按行） |
| --- | --- |
| initial-1 | U FBBBUDURR · R FBRFRDUFD · F LUUFFDUUR · D FLBBDLDDR · L DLBRLULUL · B DRLRBFFLB |
| initial-12 | U FRUFUDBRF · R LBBFRURRB · F LUUBFDDBB · D FRULDDDLR · L UUDULLFFR · B LFRLBBDDL |
| initial-2 | U DLLLURLFU · R RBUFRDLRB · F URFDFURRB · D UUDBDDRBR · L LUFLLLFDB · B BBFFBFDUD |
| initial-5 | U UFBFURRBU · R RDUBRDDRL · F DUFBFLDUB · D LLRDDFUDB · L FLFRLRBLF · B RULBBUDFL |
| initial-8 | U ULFDUBRUD · R BDUFRRUBB · F DFLLFRUDB · D BRLBDRDUR · L RFFFLDFUR · B LBFUBLDLL |
| initial-16 | U URLBULDRL · R FDFLRFUBL · F FUDUFFRLR · D BBBFDRDUU · L RDRULLLDD · B UDFRBBBFB |

8 的 U3、L3 有明显白色反光，原照片与网格仍能看见绿色侧边/下缘，因此标绿；U6 在反光之外有蓝色下部/右缘，因此标蓝。2 的 F3、L3、B3 同样从可见绿色边缘消歧。六组均无未解决歧义。16 的色块清晰、红橙可分；U 面带标志的白色中心与另五色中心均已人工检查。

每组的 `initial-N-photo-overview.png` 标出检测四边形，`initial-N-reference-grid.png` 提供无颜色文本标签的六面网格，用于复核尺寸与色块顺序。OpenCV 渲染保持前端 1600 最大边、JPEG 90 质量和面顺序，其像素插值是浏览器 Canvas 的近似。实际前端流程另由 `verify_next_speed_photos.cjs` 上传原始照片完成；该脚本记录 Canvas 缩放、JPEG 检测、正常透视采样与分类器结果，不用 OpenCV 近似结果替代页面核对。

`photo-recognition.json` 保存每组真实页面自动 Facelets、低置信度色块、检测响应、识别耗时、与人工参考的逐块差异、实际点按修正及面旋转修正。每面实际浏览器透视图保存为 `initial-N-FACE-browser-preview.png`；六面录入后的完整页面保存为 `initial-N-photo-page.png`。脚本拦截求解接口，断言求解请求数为 0，不产生最短成本或求解性能结果。

本次真实页面六组均自动匹配人工参考，逐块修正和面旋转修正均为 0；没有页面 JavaScript 错误，浏览器和识别服务均已关闭。各组仍有需要视觉关注的低置信度色块：1 为 D6、D9、B3、B6；2 为 U3、D9、L6；8 为 U2、U3；12、5、16 无此类色块。以上编号从 1 开始。识别耗时仅记录本轮普通页面上传过程，未在排除构建干扰的性能窗口采集，不作为求解基线或受控图像处理速度结论。

补充管线差异保留在 `opencv-color-regression.json`：OpenCV 近似处理的 1、12、2、5、16 通过，8 的 U1/U3 标签互换（自动 U=`FLUDUBRUD`，人工 U=`ULFDUBRUD`）。首次该组失败的标准错误在 Windows GBK 解码时出错，随后仅重试诊断并以 UTF-8 保存完整错误与分类结果，两个尝试均保留。未为通过测试改变照片参考。实际浏览器 U8 的无损透视图和自动分类均正确。

`extract_real_patches.py --browser-report` 可以直接读上述 240×240 无损浏览器 Canvas PNG，沿用精确 71×71 色块和中心环，不重做缩放、JPEG 编码、检测或透视变换。`browser-patch-color-regression.json` 记录六组实际 Canvas 像素经 `web/color.js` 分类后，与独立人工参考一致且质量有效，并记录 36 张预览 SHA-256。8、16 也通过 `real_color.test.js` 的实际 Canvas 色块回归。

另一个诊断 `browser-patch-prototype-diagnostic.json` 保留历史单原型可分性检查应用到真实 Canvas 后的结果：1 的 D9 红块单个最近原型为橙（红距离 45.88、橙 27.78），但均衡分类器输出仍为正确红色。这个诊断失败不改写为通过；原有 OpenCV 1/2 的红橙可分性断言继续保留，六组真实前端回归另检查均衡分类结果和质量。不能把“全部自动标签正确”误述成“所有反光色块都能单独最近原型定色”。

`photo-legality.json` 用独立 Python `cube_app.cubie.from_facelets(validate=True)` 验证六组颜色计数、中心、完整角/棱集合、角朝向和、棱翻转和与角/棱奇偶性；`to_facelets` 必须逐字回环一致。该检查与 JavaScript 色彩分类器独立，且不运行搜索。

复现顺序：

```powershell
python tests/render_next_speed_references.py
# 先视觉核对生成的无标签图片与 manual-photo-reference.json，再冻结。
python tests/freeze_next_speed_photo_cases.py
node tests/verify_next_speed_photos.cjs docs/benchmarks/next-speed-2026-10-02/photo-recognition.json <playwright模块路径> <python可执行文件路径>
python tests/freeze_next_speed_photo_cases.py --recognition docs/benchmarks/next-speed-2026-10-02/photo-recognition.json
python tests/verify_initial_solver_cases.py
python tests/run_next_speed_color_regression.py
# 8/16 真实色块回归使用已经保存的浏览器像素。
python tests/extract_real_patches.py --group 8 --browser-report docs/benchmarks/next-speed-2026-10-02/photo-recognition.json | node tests/real_color.test.js --group 8
python tests/extract_real_patches.py --group 16 --browser-report docs/benchmarks/next-speed-2026-10-02/photo-recognition.json | node tests/real_color.test.js --group 16
```

`tests/extract_real_patches.py --group` 白名单明确包含 8、16，并且真实颜色测试从这份独立人工参考读取六组期望值。该 OpenCV/Node 回归与真实页面结果分别保存，不能相互冒充。1、12 的已证成本仅用于历史正确性回归，HTM 为 18/17、QTM 为 22/20。
