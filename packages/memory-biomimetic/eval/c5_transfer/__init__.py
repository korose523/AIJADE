"""C5 可迁移性实验（package init）。

把 `adapter` / `fingerprint_lib` 作为包内模块暴露，使 run.py 的
`from c5_transfer.adapter import ...` 可用，同时明确本包不引入
第三方依赖（mem0 只在 run.py 内部按需导入）。
"""

from __future__ import annotations

__all__ = ["adapter", "fingerprint_lib"]