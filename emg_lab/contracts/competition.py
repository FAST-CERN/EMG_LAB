import math
from dataclasses import dataclass

from .artifacts import safe_name


@dataclass(frozen=True)
class RaceConfig:
    seed: int = 20261025
    count: int = 6
    limit_s: float = 120.0
    official: bool = False
    group: str = "未分组"
    control_mode: str = "fixed_classification"
    speed_tier: str = "basic"

    def __post_init__(self):
        if type(self.seed) is not int or not 0 <= self.seed <= 2147483647:
            raise ValueError("种子须为 0–2147483647 的整数。")
        if type(self.count) is not int or not 1 <= self.count <= 20:
            raise ValueError("每局金币数须为 1–20。")
        if not math.isfinite(self.limit_s) or not 20 <= self.limit_s <= 600:
            raise ValueError("每局限时须为 20–600 秒。")
        safe_name(self.group)
        if self.control_mode not in ("fixed_classification", "continuous"):
            raise ValueError("控制接口须为固定分类或连续速度。两者使用同一榜单。")
        if self.speed_tier not in ("basic", "advanced") or (
            self.control_mode == "fixed_classification" and self.speed_tier != "basic"
        ):
            raise ValueError("固定分类只能使用基础速度档；进阶档仅供验收后的连续/混合控制。")


REASONS = {
    "completed": "全部收集完成",
    "timeout": "时间结束",
    "fallen": "机器人跌倒",
    "out_of_bounds": "越出训练区",
    "aborted": "提前结束",
    "signal_lost": "输入信号中断",
    "slow_machine": "仿真速度不足，成绩需重测",
    "integrity_error": "程序校验失败",
    "invalid_physics": "物理状态异常",
    "clock_error": "计时异常",
    "startup_error": "启动失败",
    "replay_finished": "回放结束",
}
