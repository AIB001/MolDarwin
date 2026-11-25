"""Local hardware measurement: what this machine is, and what it should be asked to do."""

from molcat.environment.detect import detect_environment
from molcat.environment.models import (
    ENVIRONMENT_SCHEMA_VERSION,
    AcceleratorVendor,
    CpuInfo,
    DiskInfo,
    ExecutionPlan,
    FrameworkInfo,
    GpuDevice,
    HostEnvironment,
    MemoryInfo,
    PlatformInfo,
)

__all__ = [
    "ENVIRONMENT_SCHEMA_VERSION",
    "AcceleratorVendor",
    "CpuInfo",
    "DiskInfo",
    "ExecutionPlan",
    "FrameworkInfo",
    "GpuDevice",
    "HostEnvironment",
    "MemoryInfo",
    "PlatformInfo",
    "detect_environment",
]
