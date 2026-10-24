# 原生来源保真导入与自带 API Key 的文字建议

这是可直接运行的**独立、显式选择的命令行工具**。现有 GUI/扫描转换入口未被替换。

## 为什么先保留来源

S0 的 B 方案主要收益来自 PDF 原有路径，而不是一个新的专用视觉模型。
本目录把路径导入与 AI 转录分开：前者无 OCR、无模型、无 API Key；后者只产生可复核建议。
不再要求每次转换都请高推理模型重写绘图程序。

## 1. 离线导入

在仓库根目录使用独立环境：

```powershell
python -m venv .venv-native
.\.venv-native\Scripts\python.exe -m pip install -r tools/native_first/requirements.txt
.\.venv-native\Scripts\python.exe -m tools.native_first.import_pdf input.pdf --page 1 --inspect
.\.venv-native\Scripts\python.exe -m tools.native_first.import_pdf input.pdf --page 1 --output local-artifacts/native/page.dxf
```

Linux/macOS 使用 `.venv-native/bin/python`。`--page` 从 1 开始。输出包括 DXF 和 `.manifest.json`；已有文件不覆盖。
默认按 PDF 纸面 point 转毫米，不猜工程比例，不去重，不把同一路径叫成工程构件。
所有源绘制操作都保留到实体的绑定，显示的文字轮廓仍是几何，不是假称已恢复 TEXT。

当前支持：无旋转/额外裁剪的全页，线段/矩形/四边形、不透明无虚线描边和支持的多边形填充。
原生文字、图像、曲线、遮罩、透明组、任意裁剪等尚未整合，遇到时报告不支持，不导出一个假装完整的残页。
这是最初的适用范围，不是“所有清晰图纸”的定义。扫描或混合内容仍需既有链路或后续明确的新任务。

标准 DXF lineweight 为离散近似；精确源宽度在清单中保留，现有应用预览使用 P3A_STROKE 兼容表达。
该兼容字段用于预览宽度，不应当作真实扫描 DPI。端帽、接头、打印及外部 CAD 回存仍需验证。

既有 A/B 坐标合同可显式指定，不在代码中固定 W01：

```powershell
python -m tools.native_first.import_pdf input.pdf --page 1 --canvas 2174 3024 --units-per-pixel 0.10584956792964155 --output local-artifacts/native/ab-frame.dxf
```

这两个参数是成对的坐标设置，不是任何新页面的推荐尺寸。

## 2. 供应商可替换的 AI 转录建议

```powershell
# 仅检查配置和输入，不联网、不计费：
python -m tools.native_first.byok --config tools/native_first/providers/deepseek.example.json --image page.png

# 只有使用者明确设置自己的密钥并允许发送此图，才执行一次请求：
$env:DEEPSEEK_API_KEY = '<在本机设置，不要提交到 Git>'
python -m tools.native_first.byok --config tools/native_first/providers/deepseek.example.json --image page.png --execute --allow-upload --output local-artifacts/native/proposals.json
```

接口支持 `openai_chat` 与 `anthropic_messages` 两种请求格式。可配置 endpoint、模型名、环境变量名、最大输出和超时。
`providers/custom.example.json` 可改成其他图像模型的兼容端点；兼容协议不等于识别效果相同。
密钥不写 JSON、不进输出；不自动上传 PDF、扫描目录或全仓资料；发送的只有明确指定图像。
默认 dry-run；发送请求需同时有 `--execute`、`--allow-upload`。不自动重试、不跟随携带密钥的重定向。
模型结果必须通过 JSON、范围、坐标和类型检查，始终是 `AI_PROPOSAL_UNVERIFIED`。
不会执行模型返回的代码，不会自动关闭源字形，不会改写 CAD，不会把 `uncertain=false` 等同真人认证。

DeepSeek 官方在 2026-10-24 查得的文档列出 `deepseek-flash` 图像输入；示例采用该模型。
模型名、图像能力和服务可用性应在实际使用时核对。没有用户密钥的本次整合只做模拟响应和协议测试，未调用任何付费 API。
Anthropic 示例需填实际支持图像的模型名。输入同图和预算，再比较转录正确率、漏项、错误与修改劳动；不要仅比较响应是否成功。

官方协议参考：
- https://api-docs.deepseek.com/guides/vision/
- https://api-docs.deepseek.com/guides/json_mode/
- https://platform.claude.com/docs/en/api/http/messages

## 3. 已做与未做

- 30 项局部测试通过，含坐标、来源绑定、覆盖拒绝、协议、显式上传许可与不可信输出处理。
- S0 复用原 A/B 坐标：2,555 个来源路径，797 LINE、2,198 LWPOLYLINE、1,712 HATCH。
- 与 B 首版比较，几何多重集合在 1e-9 mm 舍入下相同；不是完整标签相等、整页语义认证或 GUI 验收。
- 新工具不包含 W01 固定转录、选区、真实标注、字体二进制或原始图纸。
- 本次未完成自动文字替换 GUI、任意 PDF 支持、供应商真实效果对照或扫描语义重建。

测试：`python -m pytest -q tools/native_first/tests`
依赖单独列在 requirements.txt，不修改生产环境。重新分发产品前单独核对 PyMuPDF 等依赖许可。
