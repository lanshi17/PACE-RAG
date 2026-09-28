"""孕周解析与三值适用性判断（主文档 §4.2）。"""

from __future__ import annotations

from prenatal_rag.applicability.gestational_age import (
    Applicability,
    GestationalAge,
    GestationalAgeInterval,
    apply_ga_interval,
    apply_ga_point,
)

__all__ = [
    "Applicability",
    "GestationalAge",
    "GestationalAgeInterval",
    "apply_ga_interval",
    "apply_ga_point",
]
