from enum import Enum


class ServiceType(str, Enum):
    COMPUTE = "Compute"
    DATABASE = "Database"
    OBJECT_STORAGE = "Object Storage"
    SERVERLESS = "Serverless"


class PricingModel(str, Enum):
    """Purchase option — a real dimension of the rate itself."""

    ON_DEMAND = "on_demand"
    RESERVED = "reserved"


class UsageMode(str, Enum):
    """How the billable quantity is supplied.

    FLAT: a single pre-computed quantity in the SKU's unit.
    AUTOSCALING: a series of (quantity, duration_hours) samples — e.g. an
    autoscaling group's instance count over time, or a fluctuating storage
    level — that the engine time-weights into a single billable quantity
    (sum of quantity_i * duration_hours_i) before pricing it.
    """

    FLAT = "flat"
    AUTOSCALING = "autoscaling"
