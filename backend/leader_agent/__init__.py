"""
Leader Agent：用于训练 Language Agent 的协调者。

流程：
1. 从「有问题」和「没问题」两个文件夹中随机选取图片
2. 将图片发送给 language_agent（UI 检测）进行识别
3. 若识别结果与预期不一致，由 leader_agent 修改提示词后再次发送给 language_agent
"""

from .runner import run_training

__all__ = ["run_training"]
