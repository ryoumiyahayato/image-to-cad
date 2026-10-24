# 隔离研究源码检查点

这里保存 P12、P21-C/D 和 Goal01—22 的可公开技术源码。原始真实资料编排、真实标注、逐项预测及私人恢复地址保存在本地恢复副本。完整范围见 ../docs/project/SYNC_SELECTION_20261024.json。生产入口没有导入这些研究目录。

产品环境依赖 cad_photo_to_dxf/requirements.txt；各 ML 环境是独立可选依赖，不安装到产品环境。训练代码保存不授权执行训练。Goal14—20 的 torch 运行环境及字体需要原有私人依赖。Goal01 PDF 原创样例还需要其原有 PDF 生成依赖。部分 CLI 仍明确依赖原 baseline-runtime 与 local-artifacts；公开克隆不具备真实实验的一键复现条件。

保存 Goal22 的合成比较不加载模型。从仓库根目录执行：

```powershell
python -B experiments/research_goal22_automatic_role_binding/compare_saved.py --stage "$PWD/experiments/research_goal22_automatic_role_binding/examples/SYNTHETIC-v2" --object example-1 --region r0 --candidate '3/7'
```

输入是历史原创分数机制例，返回 DIGIT_VALUE_EQUAL。automatic_write_authority 保持 false；没有完整表达或来源认证。JSON 内原有 crop/source 路径是历史出处，二进制文件未公开；纯比较命令不读取这些文件。joined-separator 的子区域歧义保留，没有在同步中改规则。
