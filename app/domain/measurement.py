from enum import Enum


class AlertType(str, Enum):
    SEVERELY_WASTED = "severely_wasted"
    WASTED = "wasted"
    OVERWEIGHT = "overweight"
    OBESE = "obese"
    SEVERE_UNDERWEIGHT = "severe_underweight"
    UNDERWEIGHT = "underweight"


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
