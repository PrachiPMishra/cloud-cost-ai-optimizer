from enum import Enum


class ForecastHorizon(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"

    @property
    def days(self) -> int:
        return {"day": 1, "week": 7, "month": 30}[self.value]


# usage_types that can be forecast. cpu/memory are monitoring gauges (not
# addressed by this phase); "cost" is the raw ingested billing figure, not
# a usage signal. Which of these is meaningful for a given resource
# ("compute hours" vs "DB usage" being both `hours_used`, just on a
# Compute vs a Database resource) is determined by the resource itself,
# not by this list.
FORECASTABLE_USAGE_TYPES = {"requests", "hours_used", "storage_gb", "network_gb"}

# Flow metrics accumulate over an interval (sum when aggregating to daily);
# gauge metrics are a point-in-time level (average when aggregating to daily).
GAUGE_USAGE_TYPES = {"storage_gb"}
