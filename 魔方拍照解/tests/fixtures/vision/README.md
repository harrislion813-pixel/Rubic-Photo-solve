# 实拍提交级回归样本

这 12 张 JPEG 来自项目的 `initial/`，总计约 2.44 MiB，包含三阶 `initial-1` 和二阶 `initial-3`。保留整张画面与原方向，最长边不超过 1600 像素，OpenCV `INTER_AREA` 缩放后以 JPEG 质量 95 保存。没有裁切网格或修正色块。

`manifest.json` 保存原图和样本的 SHA-256、样本字节数以及人工参考面贴串。三阶参考来自 `tests/initial_solver_cases.json`，二阶参考来自 `tests/real_color.test.js` 的第 3 组人工标签，以 `W R G Y O B → U R F D L B` 映射。

浏览器使用产品本身的解码、Canvas 缩放、后端检测和颜色分类；门禁直接断言自动面贴串与人工参考逐格相同，不靠缩放参数的数值保证保真，也不允许人工校正掩盖识别错误。门禁点击页面求解，通过 HTTP 获取公式，并独立回放和核对 HTM 步数。提交级只验证可用公式与候选，不断言严格最短。

```powershell
npm ci
npx playwright install chromium
npm run test:photos
```

需要已准备的 HTM 原生程序、主表和 Python 回退缓存；缺样本、哈希不符、缺浏览器或缺原生资产均失败。完整原图集仍可由原验证器的默认识别模式使用，该模式继续拦截求解请求以保护性能矩阵。
