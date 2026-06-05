"""Runtime 路径定位 helper。"""

from __future__ import annotations

from pathlib import Path


def repo_root(anchor: Path | None = None) -> Path:
    """从 anchor 向上寻找仓库根目录。"""
    current = (anchor or Path(__file__)).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
    # 打包或单独测试时可能没有 .git，退回到当前 server 包结构推导。
    return current.parents[4]
