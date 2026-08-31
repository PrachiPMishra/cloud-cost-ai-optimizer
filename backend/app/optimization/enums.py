from enum import Enum


class ScenarioType(str, Enum):
    CURRENT = "current"
    AUTOSCALING = "autoscaling"
    RESERVED = "reserved"
    RIGHT_SIZING = "right_sizing"
    STORAGE_OPTIMIZATION = "storage_optimization"
    COMBINED = "combined"


class InstanceTier(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class StorageTier(str, Enum):
    STANDARD = "standard"
    INFREQUENT_ACCESS = "infrequent_access"


class ServerlessMemoryTier(str, Enum):
    MEM_128 = "128mb"
    MEM_512 = "512mb"
    MEM_1024 = "1024mb"
    MEM_2048 = "2048mb"


# The tier/pricing-model choice used for scenarios that don't open that
# axis — i.e. "what's already deployed today."
BASELINE_INSTANCE_TIER = InstanceTier.MEDIUM
BASELINE_STORAGE_TIER = StorageTier.STANDARD
BASELINE_SERVERLESS_MEMORY_TIER = ServerlessMemoryTier.MEM_512
