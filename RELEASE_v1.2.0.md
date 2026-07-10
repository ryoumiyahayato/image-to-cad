# CAD Photo to DXF v1.2.0

本版本将手机拍摄的纸质 CAD 图纸照片转换为可继续编辑的 DXF 线稿。项目定位为半自动图纸矢量化工具，不是原始 DWG 恢复工具。

## 推荐下载

- `CADPhotoToDXF_Modern_x64_Setup_v1.2.0.exe`：Windows 10 1809 及以上 x64 的完整安装版。
- `CADPhotoToDXF_Modern_x64_Portable_v1.2.0.zip`：Windows 10 1809 及以上 x64 的便携版。
- `cad_photo_to_dxf_source_v1.2.0.zip`：完整源码。
- `cad_photo_to_dxf_legacy_source_v1.2.0.zip`：Windows XP SP3、Windows 2000 SP4、Windows 2000 Server SP4 的 Legacy x86 源码与构建链。
- `SHA256SUMS.txt`：全部发布文件校验值。

## 系统支持

### Modern x64

面向 Windows 10 1809 及以上 x64，包含 PySide6 GUI、Hough + LSD、几何清理、处理报告、人工编辑、OCR/曲线辅助识别和 DXF 回读审计。

### Legacy x86

XP/Windows 2000 兼容内容以源码和可复现构建链发布。该分支属于实验适配，尚未完成全部目标系统实机认证，因此本 Release 不宣称提供已认证的 XP/Windows 2000 安装包。Legacy 版仅保留核心离线转换流程，不包含 Modern 版的全部功能。

## v1.2.0 重点

- Windows 10 Modern x64 与 XP/2000 Legacy x86 双发行架构。
- 真实 Windows 版本和体系结构预检。
- EXIF、图像质量、纸张候选、几何有效性和空结果拦截。
- 已知纸张比例、横纵比例校准和尺寸可信状态。
- DXF R2010、毫米单位、独立可编辑实体和原子写入。
- JSON 处理报告与参数快照。
- GUI 后台任务、状态失效、进度和取消框架。
- Legacy Tk 主线程队列更新，避免旧系统跨线程 GUI 崩溃。
- Legacy 手动四角会话保持，避免导出时丢失人工校正。

## 验证状态

开发验收包含 59 项自动化测试、静态检查、Python 编译检查以及 Modern/Legacy 样例 DXF 审计。旧系统兼容仍需在 XP SP3、Windows 2000 SP4 和 Windows 2000 Server SP4 的真实或虚拟机环境完成安装、启动、导出和卸载认证。

## 重要限制

- 输出结果必须人工在 CAD 中抽查墙线、开口、交点、图层和尺寸。
- 未指定真实纸张比例且未完成双方向验证时，不能标记为尺寸可信。
- OCR、圆弧和建筑符号分类属于辅助结果。
- 严重折叠、遮挡、反光、模糊和非刚性纸张变形不能保证可靠恢复。
- 安装包未进行商业代码签名，Windows 可能显示未知发布者。
