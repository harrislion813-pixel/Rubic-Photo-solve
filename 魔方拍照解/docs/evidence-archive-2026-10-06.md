# 历史验收资料归档 · 2026-10-06

从提交 `3ef0720421b880692c5a07e16d2fbc2cd448751c` 的 Windows 工作区冻结全部 594 个已跟踪 docs 文件，共 278.66 MiB。归档先发布，再重新下载、校验全部对象并完整恢复 594 个文件，最后迁移仓库文件。

[GitHub Release 归档](https://github.com/harrislion813-pixel/Rubic-Photo-solve/releases/tag/evidence-2026-10-06) · [下载 ZIP](https://github.com/harrislion813-pixel/Rubic-Photo-solve/releases/download/evidence-2026-10-06/CubeLens-evidence-through-1.11.0-2026-10-06.zip) · [逐文件原路径与 SHA-256 清单](evidence-archive-2026-10-06.json)

ZIP 字节数：`87473020`；SHA-256：`d7a4787bcb6535914b1da3828acde6cb3c074a3364af033a9f57aa8644be7d59`。内容按 SHA-256 去重，两个相同的 formal-matrix.json 共享一个对象。ZIP 的 inventory.json 与版本化清单逐项一致。

仓库保留 379 个原有文件（18.29 MiB）：可读报告、脚本、日志、小于等于 256 KiB 的 JSON，以及人工参考记录依赖的 13 张照片概览/网格图。其余 215 个大 JSON、gzip 和截图可按下面的原路径恢复。新增索引和维护报告也计入 20 MiB 总预算。

```powershell
.\.venv\Scripts\python.exe -X utf8 tests\evidence_archive.py restore --prefix docs/benchmarks/next-speed-2026-10-02/formal-final/
# 在单独目录恢复全部原件，便于重跑历史总结脚本和核对被更新过的报告：
.\.venv\Scripts\python.exe -X utf8 tests\evidence_archive.py restore --destination artifacts/evidence-restored
```

脚本下载到 artifacts/evidence，核对 ZIP、内部库存和每个对象的 SHA-256 后才恢复。默认仅补缺失文件，保留已有工作区文件；还原目录必须位于指定目标下，禁止路径越界。原始报告/日志中的旧路径与哈希属于历史记录，仍可在完整归档中复核。新基准输出放入 artifacts/，确认需长期保留后只提交摘要。

体积门禁分两阶段完成：先冻结 8 个已有超大文件的精确哈希例外，并启用 5 MiB 单文件上限；归档验证与迁移完成后移除全部例外，启用 docs 20 MiB 总量上限。

Git 历史没有重写。工作区文件减少不代表 clone 或 .git 对象存储同步缩小；tests/check_repository_size.py 分开记录版本化工作区体积和 git count-objects 的 KiB 统计。Git 可达历史继续保留原对象，后续历史重写需另行评估。

## 已迁出的原路径

| 原路径 | MiB | SHA-256 |
| --- | ---: | --- |
| <a id="file-a21a7fa56ecd"></a>`docs/benchmarks/htm-h0-real.json` | 0.337 | `dc415541321373216eb9f6deabc93651df51c72bfe83c9cf4dec2819981434e2` |
| <a id="file-99bb7bf3d3bb"></a>`docs/benchmarks/htm-h1-real-15.json` | 0.343 | `c785ccc64fe8447217b07e3f62361792671e9a6453bd6ac7b07deffe25f4ebfe` |
| <a id="file-d6cf9ad93fe5"></a>`docs/benchmarks/htm-h1-real-final.json` | 0.258 | `88a0d4e98f868184f324854a9a34a4010c3b0fb89110e47d11a48dd9893b4405` |
| <a id="file-0887516df3ad"></a>`docs/benchmarks/htm-h1-real-release.json` | 0.253 | `728ea8a7aa1e8872fe06dafc6e57b9c475bce04589606e8ec8b8c32892c7834d` |
| <a id="file-ffc2e9eb8faa"></a>`docs/benchmarks/htm-h1-real.json` | 0.253 | `45a3dd3b815dbd3e86d0238da479ff8de8e354df3ea9540eab359ee89364d06d` |
| <a id="file-10ac562b652f"></a>`docs/benchmarks/htm-opt-2026-10-05/acceptance-summary.json` | 0.357 | `adddcf37cf03e5dd1f2b308cf65abd65ec520d90f760d21bed7f2bf1de66dfc1` |
| <a id="file-37615c221d09"></a>`docs/benchmarks/htm-opt-2026-10-05/final-default.json.gz` | 0.040 | `6ec529e35ab00ff9171a338b4449b0ecd3baf19b22b106a0c674ebdc560d70dc` |
| <a id="file-b8294228072c"></a>`docs/benchmarks/htm-opt-2026-10-05/final-random.json.gz` | 0.014 | `a463f07703ce7d205f34ec36f51392e94fadc26bb2014cbe74f1d1565644a3b0` |
| <a id="file-98787cb65078"></a>`docs/benchmarks/htm-opt-2026-10-05/final-same-tree-pair.json.gz` | 0.035 | `2140de77b3f54f8a07206891b478e27a8d975b77f1929866bb4d90b33700962f` |
| <a id="file-d323aa4ec516"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-1-baseline.json.gz` | 0.079 | `a931d7fcc7fcaa3add37a474c3a1f84ef73f8f81bc4ab62cef9927f2ff48ccd1` |
| <a id="file-9e0d6f655780"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-1-current.json.gz` | 0.040 | `d1d16c8b3b23a873f81d8232e04ec58270ae6fc8a05dc0b9b84769e3bc84b77e` |
| <a id="file-80ec595e4beb"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-12-baseline.json.gz` | 0.049 | `a596d4d60659dba1a3f02cd8a5559cc9ee746628911cae51e76333e107257772` |
| <a id="file-fe600e90c7bf"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-12-current.json.gz` | 0.044 | `25d216d076632f527ffc430270c38eccc101d6ddc0d6734777a288d6f3349a7f` |
| <a id="file-99d050c72a7e"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-16-baseline.json.gz` | 0.080 | `e284f0cb54d5f25b5595b1fa07e62402d5bacfc1239ccf144f5852192d54e4e6` |
| <a id="file-5bd074bcd933"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-16-current.json.gz` | 0.079 | `8e6324366dd99eacdac899847b72e4f7841b2bed3cb169879e2f9ecd04765d8c` |
| <a id="file-15a74b24ddce"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-2-baseline.json.gz` | 0.020 | `95ad6341a5a555be39301759d3860ce90a68238da24527842556caa29f68ce12` |
| <a id="file-1986e588f332"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-2-current.json.gz` | 0.019 | `63ac70d801e3049f11960a43d3f930aa35b74af220630f92ea90c870da900853` |
| <a id="file-732ef30863b9"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-5-baseline.json.gz` | 0.041 | `7fb6392a9e953b0952ce0886461e061934fb0e6abd16efb804ef29b150739959` |
| <a id="file-b04fb84b0398"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-5-current.json.gz` | 0.038 | `a18c31fe714f4119c90f426e79a1a22eae1634275b87e260fd943fbf6aae8cbd` |
| <a id="file-b97001d58713"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-8-baseline.json.gz` | 0.079 | `e9109636e3fcb7392d7a29a8bdc0e388b38c5b71eada81a6fe816e6922dec6b8` |
| <a id="file-7b8d95f83c51"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/0-initial-8-current.json.gz` | 0.044 | `0354c7f23a63b7268b95bda7379d53fd7b6eb93a0b597a7d9bc0dee1bf52e798` |
| <a id="file-773a2cb1a9a5"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-1-baseline.json.gz` | 0.068 | `398bd90fa79cddd74aab7042f6c3045823218f74062830ff75410b70e640d749` |
| <a id="file-655f4495b527"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-1-current.json.gz` | 0.039 | `e1e31de53c68d3be06563cdfff9458eec9d9f222ff9dee8c84706a6c366b040a` |
| <a id="file-d3bb2862b433"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-12-baseline.json.gz` | 0.048 | `b0136566e79bfb00e35c1f187825c3294fc9385caaf38ab76cabe043ae2f1016` |
| <a id="file-f394ba9f1ce8"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-12-current.json.gz` | 0.043 | `0d1e066b11ebd3338620edc87ea6203856a8261bf8067c3fa99cc1cbefe858d6` |
| <a id="file-d139d0a84df7"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-16-baseline.json.gz` | 0.079 | `83e60264f72bdea5fc78e80ff0975359c741d286f053b4422d1be16952656054` |
| <a id="file-287868f91f55"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-16-current.json.gz` | 0.079 | `b64970a62e4ea700063f2f73410b71c31d61f427bae7e20e816ee5e492849519` |
| <a id="file-23a0f01addaa"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-2-baseline.json.gz` | 0.019 | `101a7a709d93e9a615fefee78e0feb4b9d656c8ee5a11e0ad0a733dd6ea7e394` |
| <a id="file-f2eec75ab07a"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-2-current.json.gz` | 0.020 | `0324975a5136680a525edab32335028ed1e56cd9e1360656624c210cd428bded` |
| <a id="file-59395f4486a9"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-5-baseline.json.gz` | 0.040 | `059cbcd9eb34b2cfb964355a2b9eb8efe5074d8d7597b5969766889fc6cdce3e` |
| <a id="file-84a76de958fb"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-5-current.json.gz` | 0.036 | `6e0ca22ff8991a0190ea2066e1948022766384abd9039e41ae23199d5936cc35` |
| <a id="file-95f401328f7f"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-8-baseline.json.gz` | 0.080 | `b3f68f39dd91b489124cee8cb32b10ac73a2beef035bc25d6bff82a5d225e3b3` |
| <a id="file-65b5c999f344"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/1-initial-8-current.json.gz` | 0.044 | `b23e04bcf1dd2a8f0d85ffef3bb631f24bc35e6a35c50f1cbabb89716b7e99dd` |
| <a id="file-7fa0701b867b"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-1-baseline.json.gz` | 0.069 | `7e31a328f6830362405ec15c73276964ad6f8dce5fb20684cc9e972d6f099dae` |
| <a id="file-effb51b5db13"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-1-current.json.gz` | 0.039 | `4f3540653034bf76e315667c6fc8374a0f8bb48a12ba65a7448e2c1192957105` |
| <a id="file-6540016422f9"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-12-baseline.json.gz` | 0.048 | `84689d9c553abd4d0c2076dee175d1ed53543e53459d8a8d1e37ab3c3114f84d` |
| <a id="file-4d9820be52dc"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-12-current.json.gz` | 0.042 | `658e41a5553873f285baa6ba107cadbb0274c69e39140319d1afc1c6d7855816` |
| <a id="file-ad41bd4a5f5a"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-16-baseline.json.gz` | 0.079 | `1c9b095d08a92394970f84922315a032be7db4bc0d5f2909495255493ef5f051` |
| <a id="file-e48e15d777eb"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-16-current.json.gz` | 0.079 | `266f1f7d0eece5c1cbd823a58af3a45f6ea7812f546d2d439db593ffc3afd3c1` |
| <a id="file-6375b9c91327"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-2-baseline.json.gz` | 0.019 | `05e183e66da102aa0ac9364a1cbcc6b7ee3801c5dd78dc8f4d7b723688578687` |
| <a id="file-d2e1678d9746"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-2-current.json.gz` | 0.020 | `be0f636fd39b43e6131e99f7effe042fb304b7e20bafad84ef6fbdbae538c8db` |
| <a id="file-77d84e92b533"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-5-baseline.json.gz` | 0.040 | `9afd5a58dda1f97a8ad6f2fae2400a077b408a79b7770a0bf27aa495deb142bb` |
| <a id="file-2abcd2202fc9"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-5-current.json.gz` | 0.035 | `20a2f6b110afd047c6cb5d35a911d27ef01fea24d3300a9ee937e9ddb9f14e39` |
| <a id="file-d92b916822ea"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-8-baseline.json.gz` | 0.080 | `50b68ad857391f9ca06eb837ffa2de6da02e964cafa1a8240c23e71ba01d87fb` |
| <a id="file-cb7fc827bb64"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2/2-initial-8-current.json.gz` | 0.045 | `d25413137afbd06774b1940522a75538a4dade2ed76ad2d2a26a0aecf50bdecb` |
| <a id="file-b968095d0ebd"></a>`docs/benchmarks/htm-opt-2026-10-05/http-matrix-v2.json.gz` | 1.831 | `1bdab0428f8710633204af0c82faf51667f0d4cc66fe5744fc40d63492520fe8` |
| <a id="file-d82f379d54ad"></a>`docs/benchmarks/htm-opt-2026-10-05/http-smoke.json.gz` | 0.040 | `2fd6f7fd6c9955f21276e0539152e7b41a1c65a99f3fe705a15b850df564affa` |
| <a id="file-dc5018fa095c"></a>`docs/benchmarks/htm-opt-2026-10-05/p0-incumbent.json.gz` | 0.030 | `e56f8812f3b00e66535b8b8effe12b4ebc2fc317515f62aeabb4ad167d84a8af` |
| <a id="file-ca05afdfc51f"></a>`docs/benchmarks/htm-opt-2026-10-05/p1-packed-pair.json.gz` | 0.036 | `5571051e73150798bc4296385b10f5e8d7bb66a00c2ba8e9bf5ca7966e5e21eb` |
| <a id="file-f79662fdb371"></a>`docs/benchmarks/htm-opt-2026-10-05/p1-specialized-pair.json.gz` | 0.035 | `828ec0614d71c7176248ec57d574a45c366b976146187139dbce2ac024775f23` |
| <a id="file-25189db586bf"></a>`docs/benchmarks/htm-opt-2026-10-05/p2-candidates.json.gz` | 0.005 | `bc8120cb4799ba321127871dc9daee3709c5f43cc16fbcc3ceb645758f6ca2e5` |
| <a id="file-d54430a38e95"></a>`docs/benchmarks/htm-qtm-theoretical-timing-2026-10-01.json` | 0.647 | `778090d2f73e16ff0162708da121b30353dd2fc7089c013ba7708c7caccf32e6` |
| <a id="file-190842460c8f"></a>`docs/benchmarks/htm-review-2026-10-05/diagnostic.json` | 0.583 | `350559e65f49c4f428b6980a58bf4c78028e38df04eb27086a3122bf0e8ec0aa` |
| <a id="file-af27e5e94ab8"></a>`docs/benchmarks/next-speed-2026-10-02/baseline-HTM-initial-1-desktop.png` | 0.461 | `7e02dbe607bbd87cd5e0b50322134087e1ae33398f17e8a46420f2591ddfbd28` |
| <a id="file-24a10e3ab914"></a>`docs/benchmarks/next-speed-2026-10-02/baseline-HTM-initial-1-mobile.png` | 0.318 | `d8b9618c0057bc4f1662f09a52bd9bf3d2139e3d927abef6a078625077357700` |
| <a id="file-16ce8750d9ee"></a>`docs/benchmarks/next-speed-2026-10-02/baseline-HTM-initial-12-desktop.png` | 0.518 | `ca102690d2f5a22b93d66775aa7416c905a4f4a1e68b763f26b1686145dad8de` |
| <a id="file-54858500d194"></a>`docs/benchmarks/next-speed-2026-10-02/baseline-HTM-initial-12-mobile.png` | 0.341 | `744d5ac9c9444e458f9b715de952195a6d9f1e70d83a20ce73b9114e47dd5c4a` |
| <a id="file-e877a0fb7bd0"></a>`docs/benchmarks/next-speed-2026-10-02/baseline-QTM-initial-1-desktop.png` | 0.462 | `f4ca117ef0048e2382a3c8b698898db91c3afec8e1eb3637b8ab83d6f7ae948a` |
| <a id="file-0179365a39f8"></a>`docs/benchmarks/next-speed-2026-10-02/baseline-QTM-initial-1-mobile.png` | 0.318 | `0fd3521bf32467c2fc760c9543635f2e8268860e8361b20624b1281a26c88d31` |
| <a id="file-0adccd47c960"></a>`docs/benchmarks/next-speed-2026-10-02/current-HTM-initial-1-desktop.png` | 0.465 | `f782f9119f32e029312af4419aeba760df7011f4cbdd5b96c6bc6b131aa7a7ac` |
| <a id="file-532d098b1967"></a>`docs/benchmarks/next-speed-2026-10-02/current-HTM-initial-1-mobile.png` | 0.320 | `c4ce3ebb32ab8dde6b47c680dcd98a6964679031bd47d18f3ea05218ebe331ae` |
| <a id="file-3d63d8993e3c"></a>`docs/benchmarks/next-speed-2026-10-02/current-QTM-initial-1-desktop.png` | 0.462 | `07da863d3511564edadccd10f2e14b5fe6818874f738064a00abf3fcef55a179` |
| <a id="file-e7f618f0551a"></a>`docs/benchmarks/next-speed-2026-10-02/current-QTM-initial-1-mobile.png` | 0.318 | `b50ed5f33f524e5c8a7d410510de631aac6a7081f7572c78fc06391a70e3fccc` |
| <a id="file-03f5bc3253fe"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/baseline-HTM-initial-1-desktop.png` | 0.461 | `b4f0934e0c2495aae3f4f1a15bddfed36220ff922221bc0357c7c37fe66b3bf0` |
| <a id="file-9eba03ec0612"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/baseline-HTM-initial-1-mobile.png` | 0.318 | `842c5a2ab96fb5b68369ff90681061d67ba79ae8be4354c2d621384c1fa839e1` |
| <a id="file-815534e25fcc"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/baseline-HTM-initial-12-desktop.png` | 0.519 | `26af4152eade73ee3297e2f56512cebe69318522d211ff117dc2ce28cf1dd044` |
| <a id="file-72ae3b02932e"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/baseline-HTM-initial-12-mobile.png` | 0.341 | `4f405375defa25f5a38c899b335b6c74769b251533622064bbbb1320e3af1e54` |
| <a id="file-2f65e2da246d"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/baseline-QTM-initial-1-desktop.png` | 0.462 | `30d87d335ec5465ec10b305495e7de98049345f49769209af2f89cd6238412bc` |
| <a id="file-b79110cdb390"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/baseline-QTM-initial-1-mobile.png` | 0.319 | `ec3a9588815c6e0328c12f6c84d4ed5ef9eecdab85b9b4e611f4900bdadee0ad` |
| <a id="file-d5442fe5b874"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/baseline-QTM-initial-12-desktop.png` | 0.519 | `2f2d7f3d81485530427631ec98d30dcf24ca8d6f9a06c8efa9b30403a8bc2d92` |
| <a id="file-b14df5472f58"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/baseline-QTM-initial-12-mobile.png` | 0.341 | `c3e8b716f990978f2839dad0c4f81902e1986bd8e6bb61c7c784c826062754b6` |
| <a id="file-527170545f53"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/current-HTM-initial-1-desktop.png` | 0.461 | `a9c08a6ea98ff64c7ffbff6de1592f953c9bf81566f597e8ed74391e6498142a` |
| <a id="file-66c533efaba2"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/current-HTM-initial-1-mobile.png` | 0.319 | `2e9804b206a464cd67edcc24f038f955d5c0f7985b0c499ce193a65e8820f232` |
| <a id="file-c5572377a8ec"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/current-HTM-initial-12-desktop.png` | 0.519 | `9db9b80ae4b6a56aca9c2539fae94df926403b9b3e6b4d901456a2cfa19d286b` |
| <a id="file-80fd786a791c"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/current-HTM-initial-12-mobile.png` | 0.341 | `ddc017140b2d6bac48a85c4b19dfccb48b35fba5809f48889a661274cf60099f` |
| <a id="file-719d255e4282"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/current-QTM-initial-1-desktop.png` | 0.462 | `74f6f79fec29b53373f56270774e632110044c2dfb26b4d476f538d2691efee2` |
| <a id="file-a4365c842fec"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/current-QTM-initial-1-mobile.png` | 0.318 | `d750eef657229348e5ce2b64a9455bd7fc5614dcab795109c80146a4678b9976` |
| <a id="file-75703fb2aba4"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/current-QTM-initial-12-desktop.png` | 0.519 | `f52e7f7515fefc2d101bb5f26c24a301940332b2eee66c53684cedf056648ed9` |
| <a id="file-af6748f14b79"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/current-QTM-initial-12-mobile.png` | 0.341 | `49582236129a80a41a8a24f690dd843dd0042b6f9e01b76bb4920b6b072d9cde` |
| <a id="file-26aa80f412da"></a>`docs/benchmarks/next-speed-2026-10-02/default-functional/page.json` | 37.360 | `94fe2fd0fa3ac7e81e693464c0a6a697f1f22f96b5fa91ad17cf8c85c1afc90e` |
| <a id="file-31993da0cad1"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-1-desktop.png` | 0.466 | `63dd5c6599a2fd2722840a120079412266c06d51bba24ab0cf8b375f4ce07ee9` |
| <a id="file-e64fc5036f81"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-1-mobile.png` | 0.321 | `eb871396ae3957d9c44da4a33ffadcf69edca616fe05691e20b6a7edf57d8c36` |
| <a id="file-9bcce70e239a"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-12-desktop.png` | 0.519 | `4d62ccb8a70984530e998d6ebaa7f1ae8a578812ede36061f3c1c7af6c4a8bef` |
| <a id="file-9ff598f362d8"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-12-mobile.png` | 0.340 | `1c68e7ae3a501dae8844f75aefc0583f3edd1f68be0cb50b7d8079fcb428bdf7` |
| <a id="file-9b4bba941794"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-16-desktop.png` | 0.550 | `a62f9d68899b8e0b8bc6728235f235b370a9f9ff59a082d119a33bf9ae45dbe9` |
| <a id="file-e54c7ad4dab4"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-16-mobile.png` | 0.356 | `e713ef78a018b1ae0dc0a2701012cd1d4a7c86d2985f296f193e8be143fa1ff0` |
| <a id="file-22ac6351e169"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-2-desktop.png` | 0.515 | `a82b15af6d39c9987f292b14a6ffd6a92b441ee08efd6b310f819216a2151ffc` |
| <a id="file-f42d4692eefa"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-2-mobile.png` | 0.340 | `226ee1c505ab3bb3c56057d10f48e2720db9d1b50fc766e17cdb50e06529b386` |
| <a id="file-f0fc7b108db6"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-5-desktop.png` | 0.476 | `a2c73d33d48cace97e5acaca66f9e846c1d53627850e795bbfa8c844994c883e` |
| <a id="file-f293ae8cd021"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-5-mobile.png` | 0.321 | `f7eda18e5bf00eea4203ebc3ce304d301be8ed5bf60a7111cdc986fa1e257055` |
| <a id="file-398988d4f89c"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-8-desktop.png` | 0.508 | `685230a748d4ac060a0fda1ab724deacb8c16b74befed70a7248f3180223c6a1` |
| <a id="file-e4d40f64e233"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-HTM-initial-8-mobile.png` | 0.338 | `78d5cc6d38f435d2eaccaf5c802b80e1c57bbf1e5382cbc832e6e855e6c34be8` |
| <a id="file-69a205633324"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-1-desktop.png` | 0.462 | `9985f4afc105eb979e3215c781f0b43867861e92c4b8f3d489ec342b85deff37` |
| <a id="file-f63a5c14e35e"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-1-mobile.png` | 0.319 | `0f038c5d09ec6213b2c207ed55b691faffc305a6150b11e1367aba5b05081844` |
| <a id="file-11442c7c1198"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-12-desktop.png` | 0.519 | `37a72793555cf121e77431788f9cbba05b13369092bcf5c6a002b5cda7d03741` |
| <a id="file-020773f49cab"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-12-mobile.png` | 0.341 | `d4895fbab4e6997dbac4055bb66ed4044942b27143598127e53a067a062351c5` |
| <a id="file-751b9d680933"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-16-desktop.png` | 0.547 | `1d8cd7aa8c2da52b7c927cc87d4e2a90a0594c0de80dd1bcc25681aa7281ad85` |
| <a id="file-dbc996126031"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-16-mobile.png` | 0.354 | `7e948d779866a0179b9ec3746a6de40fcf5ade52c84c63405a1dc0b730216f69` |
| <a id="file-5358a65cbc0b"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-2-desktop.png` | 0.516 | `cdf5d23b3f2209b67da2ff8251c145ebe53caf37d0ad1ffb68c1741ed2089686` |
| <a id="file-ead0997eeb66"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-2-mobile.png` | 0.340 | `d944c430f6f6b4eae3837ed2cd1321bd1daa19968e135f0687e9d4d95675ac25` |
| <a id="file-83fb49afcfd9"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-5-desktop.png` | 0.478 | `704c5dc179def94841c848559e725281bf456391d9ddf2884dab33f0426df109` |
| <a id="file-bae46324eb17"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-5-mobile.png` | 0.323 | `b52d263eed1686a811e238c178309fcad75c05bf575a6866e4f2103bc756850b` |
| <a id="file-e13f3c8180da"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-8-desktop.png` | 0.504 | `942c94a0c082ac70019e0248a0c51465ed5b66728fb6436e09b2452609c74e81` |
| <a id="file-7050092a7de2"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/baseline-QTM-initial-8-mobile.png` | 0.336 | `8027e26e40fbb967406c641bdac9b3cc0890ba916803f8c02b00da2efa9f44fa` |
| <a id="file-09835a22bde5"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-1-desktop.png` | 0.465 | `4448f33f806115b050c726db783414912bdfdb5863838db9e0780633dc4df773` |
| <a id="file-e10ab05e32dc"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-1-mobile.png` | 0.321 | `3e6ce7d174b560c1182e56f62949b8a651b08c79de397fe119ac2e92fe547d92` |
| <a id="file-a4cd878d41ff"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-12-desktop.png` | 0.519 | `f49d9455ae837235f2a4ca52d8ccdd1e9650dbc30278e49396e0bf2fd25bff6b` |
| <a id="file-c730c04dcec0"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-12-mobile.png` | 0.341 | `f2f75628057c280d1287bf2a102a76a8eb8a610e06aafdadd57755da76657e10` |
| <a id="file-ef744605a5bd"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-16-desktop.png` | 0.547 | `8e4c094c8b34ddf2a15c931de515a9eb4e6d9a523800d192372567df9f46719d` |
| <a id="file-6e3c9dd18429"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-16-mobile.png` | 0.353 | `7581502f1270d737da8fcb9cf64b1c47b2b68113c7ca0ca1973ea0ecea7d4a2c` |
| <a id="file-1e9a390b9dff"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-2-desktop.png` | 0.518 | `0cfd0a04bd4aa501f0ed6e46516912f8fbdf61066d189e43046f62921bd23b1b` |
| <a id="file-021775eaa203"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-2-mobile.png` | 0.342 | `2b48d7afdc347616d7947100cbac3b2d40576d71f7297874194da53f4a790784` |
| <a id="file-3dcee42b70f4"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-5-desktop.png` | 0.476 | `c875653bd8144cc5755e95df9be6e1b5a2fb1e96211a694404ebd3bea7b0f072` |
| <a id="file-df8ca101e05e"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-5-mobile.png` | 0.322 | `d429f2265bfd56d545fa29d746ea7a7cdf1dab94c39ba47c7cb84874a1be5101` |
| <a id="file-6159e70ad841"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-8-desktop.png` | 0.508 | `bc0d6f73a798eb2998ef2b1be5ca7d4955aa07e796f7f2317028345b83375c2c` |
| <a id="file-e76a86a7a42a"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-HTM-initial-8-mobile.png` | 0.338 | `818e5762cf453af8532c6ca0ce7caeae913cad8f074d0ba8df5cbb0a25049474` |
| <a id="file-c0a977dcadab"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-1-desktop.png` | 0.462 | `a32594ab612a632c14a07eceb99cecaa5bc225298c3bda63c3b224c70454589c` |
| <a id="file-1f6cc9bf1a4d"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-1-mobile.png` | 0.319 | `f1989b3b4c726eef3069fe2e529b507cd33d154a705dfd75ace82275a86e99f1` |
| <a id="file-f91e0c817dce"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-12-desktop.png` | 0.519 | `3256bee55b010be0af0a7339148ca24b4d586bcbcae5b3bed4309bf761efef1c` |
| <a id="file-85a221f0d638"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-12-mobile.png` | 0.341 | `b756cdd570dcbf43efedc54b08d47b16c6437e741b2e8a7f11bcc011c594f719` |
| <a id="file-17ba1b778d07"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-16-desktop.png` | 0.547 | `c9251dd0981df9551616fa80ea32f405e6716ea83864c16f2510d6013b50155f` |
| <a id="file-e9d8a407108d"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-16-mobile.png` | 0.353 | `1ca3740a862c5065bb04d70c8805f7b10af8baf2a33d0bfea8e8eda2b6a40685` |
| <a id="file-9867a9057ab3"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-2-desktop.png` | 0.517 | `2ff18008d4c061d6298e29e54c4780eb2614c3de15376783c95038663f906c7d` |
| <a id="file-0b096222c07b"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-2-mobile.png` | 0.340 | `be2945a4d98f33585d48a1709774e1573521250c9c15218901477e7a71aeea81` |
| <a id="file-0afc06609fd2"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-5-desktop.png` | 0.478 | `ea3e519c86d9188f0b8236bf2bde250b8534e46348a2416b703d3b5d61ab3fe3` |
| <a id="file-7d51017a4134"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-5-mobile.png` | 0.323 | `a8e0ee56ed39589f37036a3bcc969d4fe932d4c55e85eb13f4a1d82cf51e150a` |
| <a id="file-b7dfdd0db743"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-8-desktop.png` | 0.504 | `2c929bceae920189a9918967dfa69533ad40944171ba561a0b89d051e51950cf` |
| <a id="file-114df3380d9b"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/current-QTM-initial-8-mobile.png` | 0.335 | `d0c0f0b614f9b9ea4c5337dbbc5aa28b07451c0353952a935c2debcb83333eb4` |
| <a id="file-d2b4557ffd6f"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/formal-matrix.json.gz` | 23.374 | `1c56c7ecdf9b9fd326e4d4052c18cf5b5fbdac73007446f6d9dd6517a48010b9` |
| <a id="file-f89b30c39b6b"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/summary-with-bounds.json` | 16.253 | `e9172c36d3e8da5feb0c40d861a596900d9d42fd1dc4b48a86614958414b361a` |
| <a id="file-cb61cda79c85"></a>`docs/benchmarks/next-speed-2026-10-02/formal-final/summary.json` | 16.227 | `61fa84b6a025f2cf50669d8e97d2f3df288f6092894df864f5bf518068675be3` |
| <a id="file-f34325f4a042"></a>`docs/benchmarks/next-speed-2026-10-02/formal-matrix-file-sharing-attempt.json` | 36.919 | `8b7cbf1f5dcf291c9b07cd3fde1d8b8e56afb0d6b4c34fd5b0f2465166800859` |
| <a id="file-a37609af4ef3"></a>`docs/benchmarks/next-speed-2026-10-02/formal-matrix.json` | 36.919 | `8b7cbf1f5dcf291c9b07cd3fde1d8b8e56afb0d6b4c34fd5b0f2465166800859` |
| <a id="file-687362091c50"></a>`docs/benchmarks/next-speed-2026-10-02/h2-fixed-insertion.json` | 0.539 | `d553f03b2bc8cc6b21089a080acbf47f434974a822489024169d740d6f0f376a` |
| <a id="file-0d7ba6a644c1"></a>`docs/benchmarks/next-speed-2026-10-02/h2-fixed-stable.json` | 0.522 | `c56b251cd7731efe2b728557ea0a5de15a33f4d17d27f97469555ba53bd3f970` |
| <a id="file-59243dd5dd63"></a>`docs/benchmarks/next-speed-2026-10-02/initial-1-B-browser-preview.png` | 0.092 | `18889627a133cd9b3ff656fd3565dbf78b8df07c601a263c95ea75dab14d73ee` |
| <a id="file-48e8253e2be2"></a>`docs/benchmarks/next-speed-2026-10-02/initial-1-D-browser-preview.png` | 0.098 | `8f5eb5a51ff979aa05746f9f343df25b5535630f9101a6bd85f076a015814b98` |
| <a id="file-83aba42c585f"></a>`docs/benchmarks/next-speed-2026-10-02/initial-1-F-browser-preview.png` | 0.066 | `9b62a38b4f76b8d0e38b58ff93620e4180b3a42194054cff559a90ba1b8b2bdb` |
| <a id="file-e968cb81e0e9"></a>`docs/benchmarks/next-speed-2026-10-02/initial-1-L-browser-preview.png` | 0.075 | `82da67c36016fe9eeef251d6920580133b3b602aa969fd6a648c184850aaba92` |
| <a id="file-f182593c3aa9"></a>`docs/benchmarks/next-speed-2026-10-02/initial-1-photo-page.png` | 0.455 | `deb6788d063c4602e9846de98e75ddcf62251e6fd3a317391016aa7b2982e211` |
| <a id="file-70b7797a20a1"></a>`docs/benchmarks/next-speed-2026-10-02/initial-1-R-browser-preview.png` | 0.071 | `ffa92eaf8952f2e0b9025acd5c6710703afca365531afd30c3ffdfb140b897c6` |
| <a id="file-2924e3eb4814"></a>`docs/benchmarks/next-speed-2026-10-02/initial-1-U-browser-preview.png` | 0.080 | `e6a216f70497db52e75145f08dd152b3f681a240d47c835f97320ff1ae3e4eb0` |
| <a id="file-6ff81ca781dc"></a>`docs/benchmarks/next-speed-2026-10-02/initial-12-B-browser-preview.png` | 0.096 | `4ec2fd6917a0ad2325f20444726ea94a3bd9350aaea550e67fa2dbe1ad12ad8e` |
| <a id="file-fd411b5cf995"></a>`docs/benchmarks/next-speed-2026-10-02/initial-12-D-browser-preview.png` | 0.104 | `5f0529381190f6f7fdfb18d636483483281bf73c1f40d3b25b646fb6f9292125` |
| <a id="file-110d30d02bcf"></a>`docs/benchmarks/next-speed-2026-10-02/initial-12-F-browser-preview.png` | 0.097 | `7aab44b217b4de187b22e7b374629eadcbcc0f8af3ea1735dbc14c2c81a45864` |
| <a id="file-e07ad22e5f92"></a>`docs/benchmarks/next-speed-2026-10-02/initial-12-L-browser-preview.png` | 0.104 | `ea0a400ebe7934e617c17524647af600f6175aa4076b4b01d09cad188bb394e2` |
| <a id="file-bc311323a9e2"></a>`docs/benchmarks/next-speed-2026-10-02/initial-12-photo-page.png` | 0.513 | `10789482b0c10cb11a7d21e1711fafc7ebae952587cdcb8f71d53bb23140a387` |
| <a id="file-0431f48e5bbc"></a>`docs/benchmarks/next-speed-2026-10-02/initial-12-R-browser-preview.png` | 0.103 | `4fe1ca22415ac94a11da825dcd9e5617063d3e79478202fd96075d4ca5ab2440` |
| <a id="file-34505ab23e3a"></a>`docs/benchmarks/next-speed-2026-10-02/initial-12-U-browser-preview.png` | 0.102 | `85594bec8dabf0484570a5eed64f904604331421b72f1e0d77299ef1d868a9c3` |
| <a id="file-008810e7dc8d"></a>`docs/benchmarks/next-speed-2026-10-02/initial-16-B-browser-preview.png` | 0.100 | `1f166c9e5ee154b409bc4885b64a53ddb5fe33dd8e24fe1feecfe12d0cec1f03` |
| <a id="file-d9b710324045"></a>`docs/benchmarks/next-speed-2026-10-02/initial-16-D-browser-preview.png` | 0.100 | `ff28c20c3b4924c459fa670f65df3e83646f32139243d99b26d1cef5d39aa79c` |
| <a id="file-95ed6a10c739"></a>`docs/benchmarks/next-speed-2026-10-02/initial-16-F-browser-preview.png` | 0.109 | `59b42dbd0daacf27787bf7a6490cbc520226d1748b8db22356bdf2749db6a869` |
| <a id="file-a338d1625dab"></a>`docs/benchmarks/next-speed-2026-10-02/initial-16-L-browser-preview.png` | 0.106 | `b992254b9bad3791b36ecec8e04c72eff277b4a1580bb8f9e209f4e3245d8261` |
| <a id="file-8d3a70bb347f"></a>`docs/benchmarks/next-speed-2026-10-02/initial-16-photo-page.png` | 0.538 | `adedfd12b50af8d1dd9162cb024861f5798bc3ae3ce901c327b29baedfb21b6b` |
| <a id="file-56b3d52ac2fa"></a>`docs/benchmarks/next-speed-2026-10-02/initial-16-R-browser-preview.png` | 0.110 | `4c4f417691de6838f5a5b8cb7ebab6e53a3b0311f7cc3339e7ffa9c57e3897e4` |
| <a id="file-da174f5c9712"></a>`docs/benchmarks/next-speed-2026-10-02/initial-16-U-browser-preview.png` | 0.107 | `95dfb3ed42f031114ec6ca0178692d8963ca3cb82f8a30af0a1308df217ad123` |
| <a id="file-29980d25a181"></a>`docs/benchmarks/next-speed-2026-10-02/initial-2-B-browser-preview.png` | 0.106 | `d78adce309ec110f2085fa722e41d665fbb006ca8beb0b332e05381aedd845bc` |
| <a id="file-83dd62bf6889"></a>`docs/benchmarks/next-speed-2026-10-02/initial-2-D-browser-preview.png` | 0.098 | `6661fabeb8d796f253a07feb11209f5dc4727aa011837e78bfaff868a1544d38` |
| <a id="file-2f24fd6d37e5"></a>`docs/benchmarks/next-speed-2026-10-02/initial-2-F-browser-preview.png` | 0.106 | `74c9ec3c92b6beca01ab375758c6d5f221842dd1e47fe535da9d24bd41ea2279` |
| <a id="file-b8938b2cb81b"></a>`docs/benchmarks/next-speed-2026-10-02/initial-2-L-browser-preview.png` | 0.104 | `759cc423cc6e47234c8fb502e211d87b4f651c328ed631884ea2147b2a64aee2` |
| <a id="file-81b0534c2b61"></a>`docs/benchmarks/next-speed-2026-10-02/initial-2-photo-page.png` | 0.513 | `c8ed38eafae371f93c697017c71941f25b4ff6a17964c8dcaa15dafb6d9f638f` |
| <a id="file-827d1e3dd755"></a>`docs/benchmarks/next-speed-2026-10-02/initial-2-R-browser-preview.png` | 0.099 | `aa67e788f779ec8e8944e286f675c0500523b4106d9a6dc127e5a4808929a5d0` |
| <a id="file-86c9b45c0737"></a>`docs/benchmarks/next-speed-2026-10-02/initial-2-U-browser-preview.png` | 0.095 | `9acba069cd1263558bb8e38c7ff4f8292ec827b8fdabc1967e8581f3f4cf1c86` |
| <a id="file-1925ac650801"></a>`docs/benchmarks/next-speed-2026-10-02/initial-5-B-browser-preview.png` | 0.091 | `766cf4557d19f24f772b86a6bb251045e35a1db1b9203fc72710b521bd1cac1a` |
| <a id="file-61611a08f18f"></a>`docs/benchmarks/next-speed-2026-10-02/initial-5-D-browser-preview.png` | 0.086 | `4dab668beb869477ef6c316c97fa8241627cddd5779d6070a41f5583d48c5a6a` |
| <a id="file-6621f628cdad"></a>`docs/benchmarks/next-speed-2026-10-02/initial-5-F-browser-preview.png` | 0.092 | `d34a5d50a8f80444d8fc9a1e7c8b1cc8b36a5f04a4a1a7004acc92cf67b675e6` |
| <a id="file-9a2b6ef22233"></a>`docs/benchmarks/next-speed-2026-10-02/initial-5-L-browser-preview.png` | 0.097 | `a2d06b551978398742cbf9e1d9f98753b42cf0c0e945bec10041b72202ffa491` |
| <a id="file-1677f9c647ef"></a>`docs/benchmarks/next-speed-2026-10-02/initial-5-photo-page.png` | 0.471 | `dd68d1b91cf4ff41ba6b7de23bd28862a94ed39aa7c1368bc20d656323588386` |
| <a id="file-83c9dfc50bde"></a>`docs/benchmarks/next-speed-2026-10-02/initial-5-R-browser-preview.png` | 0.090 | `27b8e5b7725b2929313dd8b0a51a467a4d847ca907e6ddcde718a3145be1dba0` |
| <a id="file-ad685549e886"></a>`docs/benchmarks/next-speed-2026-10-02/initial-5-U-browser-preview.png` | 0.100 | `e31555613ba2eb29f5eeb0a61b360cae6d60c1aa0e748eae320cdddd33a87495` |
| <a id="file-7b91739fccac"></a>`docs/benchmarks/next-speed-2026-10-02/initial-8-B-browser-preview.png` | 0.086 | `0e666adbfa2e2cc65d8186990924dc118eb879a5601de32e9949a9e9469d5694` |
| <a id="file-8ff09f6fbbf5"></a>`docs/benchmarks/next-speed-2026-10-02/initial-8-D-browser-preview.png` | 0.094 | `4337241526fa9f2e13284153014f9e1ea18f18c80f45fde2972c6e8335ac76fc` |
| <a id="file-1b6f9e02b934"></a>`docs/benchmarks/next-speed-2026-10-02/initial-8-F-browser-preview.png` | 0.099 | `b25146429fc77b0e858e4ead50cd26146b320d12ad47a53d1cc6fb7cf69135af` |
| <a id="file-f4db8d976e9c"></a>`docs/benchmarks/next-speed-2026-10-02/initial-8-L-browser-preview.png` | 0.108 | `6ee5bc73067875a3c61283938e0b402dbc14bebad90436b9d0bb29ab0dcb29f6` |
| <a id="file-8e337cb65d86"></a>`docs/benchmarks/next-speed-2026-10-02/initial-8-photo-page.png` | 0.500 | `f286afb0f76322ed56297e409123641730c6186846760057b01ef06320dd812b` |
| <a id="file-91c72ba22bff"></a>`docs/benchmarks/next-speed-2026-10-02/initial-8-R-browser-preview.png` | 0.110 | `1b478626e2ad589847166cf72c2dfd0254aa4abb9b53f338d70b99fa41e1a51c` |
| <a id="file-1e4711f526f5"></a>`docs/benchmarks/next-speed-2026-10-02/initial-8-U-browser-preview.png` | 0.081 | `526e7cceafd4f5a0f25fc14b1b785d854a2bc6475a258574df206dcde4959e39` |
| <a id="file-6bce614bc8c2"></a>`docs/benchmarks/next-speed-2026-10-02/q1-pair.json` | 0.606 | `63308ea8a5e0ad1a294017a5c81bf8943d972094d85848ed528d153d2528ca46` |
| <a id="file-3576f55937fc"></a>`docs/benchmarks/next-speed-2026-10-02/q2-late-tail-production.json` | 5.424 | `75685985bc7232cf412e3439918c0abaaef889363aaaed6054464ef756a0d075` |
| <a id="file-264003b794ba"></a>`docs/benchmarks/next-speed-2026-10-02/q2-late-tail-unmanaged-loader-attempt.json` | 3.959 | `5bc65cb97e7d66757654b78a5ff68de5fa6adb09c3689b359018fc8f9ce8270e` |
| <a id="file-202ce9b4d5e6"></a>`docs/benchmarks/next-speed-2026-10-02/q2-late-tail.json` | 3.959 | `5bc65cb97e7d66757654b78a5ff68de5fa6adb09c3689b359018fc8f9ce8270e` |
| <a id="file-d7430d098f6a"></a>`docs/benchmarks/next-speed-2026-10-02/qtm-bounded-reuse-repaired.json` | 0.394 | `f5935f3fd6a83596932bb85c00949e8e447141604cade39fa0a6ba303abec8b2` |
| <a id="file-a60475766495"></a>`docs/benchmarks/next-speed-2026-10-02/regression-details.json` | 1.196 | `f27e6d8157752c0bd155fb7ac4280713937774219db130997b6b2fe60b8db643` |
| <a id="file-db1a3d7428c9"></a>`docs/benchmarks/qtm-production-review-2026-10-01/fixed-layers.json` | 0.296 | `c15e5347e60980c4e0d033728f02084a148a81690a94b5c59a3deb007fb2f8b0` |
| <a id="file-417605aa2fdc"></a>`docs/benchmarks/qtm-production-review-2026-10-01/http-staged.json` | 0.639 | `b779ba32dbbb9fee75693d1f78f78de4def746d6cc90dc3f2e9718c1f48dcaef` |
| <a id="file-1866c3d73edc"></a>`docs/benchmarks/qtm-production-upgrade-2026-10-01/baseline-fixed.json` | 0.296 | `8dfd1e1b40e29158ff461fe00208bf756f1f953d5d46736fca8ff08c4a08ef65` |
| <a id="file-06cc3d449bc1"></a>`docs/benchmarks/qtm-production-upgrade-2026-10-01/baseline-http.json` | 0.407 | `5943729520f8b97373e3fcd4cfa8f19453feca3b99f47342bb1e426fd578f3b8` |
| <a id="file-ebb569f6885e"></a>`docs/benchmarks/qtm-production-upgrade-2026-10-01/current-fixed.json` | 0.299 | `7dfb160b0081a298f75a86867446999c6e17183ad98ba3abf9e36d2cd511954a` |
| <a id="file-f387a295c34d"></a>`docs/benchmarks/qtm-production-upgrade-2026-10-01/initial-1-mobile.png` | 0.321 | `db4a7d53a47d1cf154938f816cf51838f81e7d601cf9be0977697e9c2678f129` |
| <a id="file-92876ce15013"></a>`docs/benchmarks/qtm-production-upgrade-2026-10-01/initial-12-desktop.png` | 0.520 | `a65691746f76068b64b4ea6913127dc757db0ae7ae9f0527ebd9fd0744eb4916` |
| <a id="file-560817a6310f"></a>`docs/benchmarks/qtm-production-upgrade-2026-10-01/package-page.json` | 0.403 | `61d44e0f8a0ba353da7c8d2e8a0b0bce193586b26ff0688f8ffc3fb970f20541` |
| <a id="file-5b4d729db039"></a>`docs/benchmarks/qtm-production-upgrade-2026-10-01/scanned-strong-first-http.json` | 0.360 | `072c53d8a3117bc8fd007be5539131f837cba5a1a666a817f8efd3996a26bc28` |
| <a id="file-a81ca1e7b020"></a>`docs/benchmarks/qtm-production-upgrade-2026-10-01/strong-first-http.json` | 0.448 | `eda01cb2d9e9195217ba26284ecb8ff3691b749f7d3f1232249973cf78981010` |
| <a id="file-bb894e74406d"></a>`docs/benchmarks/qtm-q0-real.json` | 0.327 | `5ed94c1f02b700d2d09dba496f6bdb86502158fd3b7900cfb78069bd37d464c7` |
| <a id="file-be0f2a26d202"></a>`docs/benchmarks/qtm-q0-short-15.json` | 0.407 | `5bd689d3b662de99284bce75429eb9910a1b7a0298fe73501964e917900be532` |
| <a id="file-409ac446cfc5"></a>`docs/benchmarks/qtm-q0-short.json` | 0.347 | `a3de918735e3908b208e54b9cc68ace471348eb8b2a1203153deaedc17701953` |
| <a id="file-da1040590c8c"></a>`docs/benchmarks/qtm-q1-known15-retest.json` | 0.253 | `1e1e610d43d9f849753ef6c563d0b6e9af8835a04852d77f3d27c2aaf6e5fe38` |
| <a id="file-83fb8e9e8477"></a>`docs/benchmarks/qtm-q1-real-release.json` | 0.531 | `66a7fc0939f48abb1f4604f691d088dda7afc5822f41ccafa69cda96b3e783ba` |
| <a id="file-a5a0c1540213"></a>`docs/benchmarks/qtm-q1-real.json` | 0.412 | `a025a5d95e8a66482b7b582ada23ec9294786f9d2332d45fb857d0d0f02371db` |
| <a id="file-7564010d6120"></a>`docs/benchmarks/qtm-q1-short-15.json` | 0.418 | `1c777ede780c04a1e87b219e71183a178aaf1eb2d497da2c615e899d1ebad330` |
| <a id="file-073d8a61ca61"></a>`docs/benchmarks/qtm-q1-short.json` | 0.359 | `bb5e670e230cc048fe0d96ab4bd5599c8a9b1bcfd38ea415d4833b67e3f168d8` |
| <a id="file-35eb566890ca"></a>`docs/benchmarks/qtm-speed-final-fixed-layer.json` | 0.296 | `07728d477aa64dfb6197f0022b4f0890995c3790add46f3e5005f75aaeb71dd7` |
| <a id="file-0f82cb0881e6"></a>`docs/benchmarks/qtm-speed-fixed-baseline.json` | 0.274 | `b070dd94d8fd2cf2f632be77d457a1427d06d5defac061f35b71c176e141bded` |
| <a id="file-3f752c5ab7ac"></a>`docs/benchmarks/qtm-speed-package-page-acceptance.json` | 0.606 | `cdd1c597e38c03ae040b05a0afade4979b63c679a26f088ded230c95bb0da088` |
| <a id="file-621fc7f09108"></a>`docs/benchmarks/qtm-speed-prefetch-paired.json` | 0.581 | `62318b464c0a3341f4d24ca39e225251bad940f3771f08b4745cefa20937faa8` |
| <a id="file-940b73f11bb7"></a>`docs/benchmarks/qtm-speed-slice-paired.json` | 0.581 | `c287020f10889b3475a8853ddc327b073d646ea797c9f39018d756a5703eb800` |
| <a id="file-aec7e85af74c"></a>`docs/benchmarks/qtm-speed-staged-baseline.json` | 0.311 | `5e7c037647d7400c2ada9f8559b9674e8f8d375e6d1d149a6718fa67a012e9e0` |
| <a id="file-8c5edb579b5e"></a>`docs/benchmarks/qtm-speed-staged-final.json` | 0.364 | `1a4fcecd0f05bfa61023e902f68fca0a1596f9697d0cefbf4f5b202ee6d8b7f9` |
| <a id="file-6de9215357a7"></a>`docs/benchmarks/release-1.10.0/package-page.json` | 0.412 | `804e461bd8b7c0138a98f80ff71a488d487dccd1604ebb50585d8f5d136b4b83` |
| <a id="file-15a8023d2bf1"></a>`docs/benchmarks/release-1.10.1/initial-1-desktop.png` | 0.464 | `30be5c910d82b7af06c82d07367cf75ad92a765211e66dc83bbf04b88d5d87e8` |
| <a id="file-b4b5f49418c4"></a>`docs/benchmarks/release-1.10.1/initial-1-mobile.png` | 0.320 | `a3f30ac37863f3b486db488d55547a0c9113b858dc35990f2f2cf1f9801d569a` |
| <a id="file-d022f8345d51"></a>`docs/benchmarks/release-1.10.1/initial-12-desktop.png` | 0.519 | `3863522bd4c7934d084c89af56541993a8971dbb461e838a0fa68a09f19362b0` |
| <a id="file-d2e6d5d42edb"></a>`docs/benchmarks/release-1.10.1/initial-12-mobile.png` | 0.341 | `318e67e9fd2f1e44674a355aacf9f1c9311db220405453852ce04a10b39dbb52` |
| <a id="file-2f4545fe2cbc"></a>`docs/benchmarks/release-1.10.1/package-page.json` | 19.782 | `e18d39fed31c7c6d501054aab6aa8e9b7c778cfbc07ce618a1d221bc481a84e8` |
| <a id="file-c8d77d1cca2f"></a>`docs/benchmarks/release-1.11.0/portable-http-final.json` | 0.752 | `025d69b3be0edcd7ec24dba7d885f77598f9df871b1a7eb40fc9912b32eceb41` |
