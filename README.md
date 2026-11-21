# Image-to-CAD — 图片/PDF 重新生成可编辑 CAD

**研发版：`0.3.0-dev` · 整体产品 `LOCAL_NO_GO`；`main` 持续保存最新经过验证的有效开发源码，不是正式发行版。**

**[产品合同](docs/project/NATIVE_OBJECT_PRODUCT_BASELINE_20261120.md)** · [当前任务](docs/project/CURRENT_TASK.md) · [项目状态](docs/project/PROJECT_STATUS.md) · [Agent 指引](AGENTS.md) · [最新研发 PR #42](https://github.com/ryoumiyahayato/image-to-cad/pull/42)

## 我们要得到什么

使用者提供扫描图片、TIFF 或 PDF，软件利用**固定规则、图像算法、OCR、机器学习和必要的图形约束**识别并重新绘制，输出具有合理对象边界的二维 DXF：

- 完整的 LINE、ARC、LWPOLYLINE 等独立线条与曲线；
- 可整体操作的门、房号、符号和墙段；内部用合理的原生图元组织；
- 内容正确、可编辑的 TEXT/MTEXT；字体不要求与旧扫描逐像素完全一样；
- 保留真实开口、短线、邻线、图框、标注、LOGO/签名等必要内容；
- 确实无法辨认时，在正式绘图区留白并**明确标记来源与待修位置**。

**不要求算法理解工程语义；识别与“读懂”的概念不同。** 能按有依据的规则恢复完整、可删改的对象，即是有效的技术路径。不能把像素小碎线、HATCH 色块或整个背景图像冒充完整 CAD 对象。

交付以**实际保存 DXF**为准，重新打开之后需要能够删、移、改，且旧对象/邻居保持。像素覆盖率、测试数和实体数量均只是诊断，不代表产品成功。

## 当前实际实现范围

`main` 目前已包含经六项工作流通过的原生对象识别开发基线 `c73d03f`。代码有 NativeJobManager / worker、正式 CLI/GUI 及可显式选用的 legacy 路径。使用条件和资源版本见 [复现说明](docs/native/REPRODUCE.md)。

该已验证开发版在**有限输入**上完成了房号、文字、门、部分墙组及路径的原生 DXF、来源核对和实际编辑；冻结 A2 四分之一区域的一份检查点有 **359 个正式对象**，但还有大量未重建内容，**不能把359当成完整工程对象总数或正确率**。

后续的单 MTEXT 源排版试验及「BLOCK 内三 TEXT」试验都保留了识别/排版价值；后者在 LibreCAD 普通保存后出现 `INSERT.zscale=0`，使完整逆变换失败。**它们不作为当前可采用的默认输出路线**。同类兼容缺陷需要一次统一的跨 CAD 验证，而非为每条注释无限调参。

[PR #42](https://github.com/ryoumiyahayato/image-to-cad/pull/42) 保留后续未合并实验；其当前提交的 Linux 静态检查和 Windows 字体/许可证资源测试有未通过项，不能直接覆盖主线。修好并验证的代码可逐批并入 `main`，不需要等正式产品 GO 才合并。

## 从源码运行

本仓库的原生开发环境已在 **Linux x86_64 / Python 3.12** 的指定依赖与字体/模型条件下验证。具体输入命令、资源校验与无缓存运行使用 [docs/native/REPRODUCE.md](docs/native/REPRODUCE.md)，不要根据旧临时路径执行。

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r cad_photo_to_dxf/requirements-native.lock
.venv/bin/python maintenance/check_native_resources.py
.venv/bin/python cad_photo_to_dxf/main.py
```

首选交付 DXF，比例来源不足时使用纸面毫米；不能把 DPI 冒充工程设计比例。Windows CI 的旧软件构建/冒烟已通过，但**最新版原生识别链路的干净 Windows EXE 用户验收仍未通过**；Android APK、DWG 全流程和跨 CAD 完整性均待验证。

## 研发及合并原则

每轮以一项**中等规模、能增加实际内容**的任务推进：代码＋真实 DXF＋邻居保护/必要反例＋冷读/编辑检查。正确结果进入 `main`；失败研究保留在私有证据和临时非默认代码，不作为产品成果。同步前核对远端 HEAD、CI 和当前实际 DXF；合并之后清理冗余分支，不强推、不重写历史、不公开受限原图或字体模型。

当前目标仍是冻结旧图连续四分之一区域的完整内容恢复。最终人工验收要求包括全部遗漏补绘、核对、纠错：**修图总人工时间不超过同范围、同质量从零重画的一半**。尚无工程师实测，不能声称达到目标。

历史日期状态与旧像素/HATCH研究仅作证据参考，不再决定下一步产品研发优先级。
