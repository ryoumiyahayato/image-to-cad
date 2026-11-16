# CPython 3.12 的 Qt 单例返回验证 — 2026-11-16

基于实际 PR #36 合并提交 `66a1202d88972e97183b146e6c469a88e5dd2cb8`，在独立分支 `fix/py312-singleton-validation-20261116` 准备最小测试修正。只改变 `test_native_qt_exit.py` 的验证合同和本说明，没有改变应用、依赖范围、几何或来源规则。

## 为什么要区分版本

原测试在 CPython 3.12.14 / PySide6 6.11.3 下观察到 True 的 `getrefcount` 在 256 次调用后由 4,294,967,868 降至 4,294,967,612。独立子进程对照保留原 32 次预热，以 Qt `isEmpty()` 和 Python 内建 `bool(1)` 分别运行：两者都依次产生 −256、−317、0、0、0，最终停在 4,294,967,295；后续调用批次为 512、1,024、4,096、4,096。False 和 None 对照稳定，四个诊断进程均正常退出。没有只对 Qt 调用成立的持续下降证据。

这组数值是诊断结果，不是测试容差或放行常量。安装 wheel 为 cp310-abi3；本机 3.12.14 头文件的 immortal sentinel 是 UINT_MAX，兼容注释说明旧扩展可以改变这些计数。没有声称定位到了造成初始增加的具体 Qt C/C++ 调用。

官方 [sys.getrefcount](https://docs.python.org/3.12/library/sys.html#sys.getrefcount) 说明 immortal 计数不对应真实引用数量；[True/False](https://docs.python.org/3.12/c-api/bool.html) 和 [None](https://docs.python.org/3.12/c-api/none.html) 自 CPython 3.12 起为 immortal。[PEP 683](https://peps.python.org/pep-0683/) 解释旧 ABI 对计数的操作及这种数值语义边界。因此，原失败不能仅据精确整数变化认定 Qt 返回所有权不平衡。

## 修改后的检查

- 所有环境保留两个实际 Qt 返回路径，逐次检查 32 次预热和 256 次正式调用都返回预期单例对象，不跳过整个测试。
- CPython 3.11 和其他非本次已知 immortal 情形仍严格要求前后计数相等，没有增加容差。
- CPython 3.12+ 的这两个已知 immortal 单例不使用精确计数变化作为所有权证明；计数仍输出用于诊断。
- 删除 bound method/lambda 与 path、执行 GC 后，弱引用必须表明 path wrapper 已销毁；子进程继续要求正常退出，保留 faulthandler 和超时。

原失败、内建 bool 负对照和完整环境数值保存在私有复现资料 `continuation_compatibility/PY312_REFCOUNT_DIAGNOSTIC.json`。修改不撤销原 Python 3.11 所有权回归，也不改变 PySide6 `<6.12` 的既有依赖限制。requirements 仍为 Python 3.11+，不能把 3.12 简单归为不支持。

## 实际验证结果

2026-11-16 在隔离的 Linux CPython 3.12.14 环境执行以下完整本地范围。环境按仓库现有 requirements 安装，未改变依赖声明；实际为 pytest 8.4.2、PySide6 6.11.3、NumPy 2.5.5、SciPy 1.18.1、Shapely 2.2.0、OpenCV 4.14.0.94、ezdxf 1.4.5、ONNX Runtime 1.32.0、Ruff 0.17.5、mypy 1.20.2。原研究环境保持不变。

| 验证范围 | 实际结果 |
| --- | --- |
| 完整 unit | 1,728 PASS / 26 SKIP，零失败、零错误 |
| 独立 drafting | 88 PASS，零跳过 |
| `maintenance/preservation_check.py` | EXACT；既有有限迁移、身份投影与独立 LINE 来源 ledger 均保持 |
| 应用与 drafting 两组 Ruff | PASS |
| 规定四文件 mypy | PASS |
| 应用与 drafting 两组 compileall | PASS |
| 仓库卫生 | PASS，0 finding |

26 项跳过分别是 18 项缺少本地 TrueType 测试字体、8 项未准备 P2C 官方候选运行资源；本次 Qt 测试没有跳过。修改后的两个 Qt 用例也分别在 CPython 3.11.18 与 3.12.14 下 focused 2 PASS；3.11 的前后计数仍严格相等。本轮没有重复已有的 3.11 完整 suite。

所有门槛通过同一私有离线运行器执行：导入 ONNX Runtime 前禁遥测，进程级拒绝网络系统调用，并记录 IPv4/IPv6 socket 自检为 EPERM。启动时 HEAD 为实际合并提交 `66a1202d88972e97183b146e6c469a88e5dd2cb8`，叠加本文件所述测试改动；运行前后 296 个源码文件字节相同。源码 inventory SHA-256 为 `e3dfe61f3b1b8a8def58f4d12f15d280d318719495a3237b17ea36e7e2359e25`，受测测试文件 SHA-256 为 `00205e47f34630ef5ec544128201e47054961dce3431ef13113a23d256fd2977`。这里只按受测字节绑定结果，不把随后形成的提交误记为测试启动 HEAD。

完整命令、时间、环境、JUnit、各门槛日志及前后 inventory 保存在私有复现目录 `continuation_compatibility/py312_validation/`；汇总 `full_summary.json` SHA-256 为 `05b86b22af1271f96098590f3a7bb6d77c8980a99a82d97e5f50320d93892528`。首次编排在 unit、drafting 和 EXACT 成功后，因已有 focused `ruff.log` 而拒绝覆盖输出；异常另存，核对源码未变后只续跑尚未启动的静态门槛，完整 Ruff 使用 `full_ruff.log`，未重跑或改写已完成结果。

这是完整声明范围内的 Linux Python 3.12 自动验证结果；没有执行 Windows Python 3.12 打包安装、目标 CAD GUI/DWG 或新的精度与真人劳动验收。后续远端 CI 按实际发布 head 分别核实。
