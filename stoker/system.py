"""System health via NVML — actual hardware readings only.

Oracle P1-6: null for unavailable values, timestamps on everything,
telemetry failure distinguished from hardware failure. No fabricated data.
Oracle P0-2: fan is tristate (unknown/running/stopped). Our independently
powered blower may not expose RPM to NVML — unavailable RPM is UNKNOWN,
never zero.
"""
import shutil
import time
from typing import Optional

import psutil

from .models import FanState, HealthInfo, utcnow

_boot = time.time()


def _nvml():
    try:
        import pynvml
        pynvml.nvmlInit()
        return pynvml
    except Exception:
        return None


def get_gpu_memory() -> tuple[Optional[int], Optional[int]]:
    """Return (total_bytes, used_bytes) or (None, None) if unavailable."""
    nvml = _nvml()
    if not nvml:
        return None, None
    try:
        h = nvml.nvmlDeviceGetHandleByIndex(0)
        mem = nvml.nvmlDeviceGetMemoryInfo(h)
        return mem.total, mem.used
    except Exception:
        return None, None


def get_health() -> HealthInfo:
    temp = util = throttling = None
    fan_state = FanState.UNKNOWN
    fan_rpm: Optional[int] = None

    nvml = _nvml()
    if nvml:
        try:
            h = nvml.nvmlDeviceGetHandleByIndex(0)
            try:
                temp = float(nvml.nvmlDeviceGetTemperature(
                    h, nvml.NVML_TEMPERATURE_GPU))
            except Exception:
                pass
            try:
                rates = nvml.nvmlDeviceGetUtilizationRates(h)
                util = float(rates.gpu)
            except Exception:
                pass
            try:
                # Throttle reasons bitmask — any bit set means throttling
                reasons = nvml.nvmlDeviceGetCurrentClocksThrottleReasons(h)
                throttling = reasons != 0
            except Exception:
                pass
            try:
                # Fan speed percent; RPM rarely exposed on datacenter cards
                pct = nvml.nvmlDeviceGetFanSpeed(h)
                fan_state = (FanState.RUNNING if pct > 0
                             else FanState.STOPPED)
            except Exception:
                # NVML_ERR_NOT_SUPPORTED etc. → fan unknown, NOT zero
                fan_state = FanState.UNKNOWN
        except Exception:
            pass

    try:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
    except Exception:
        cpu = ram = None

    try:
        disk_free = psutil.disk_usage("C:\\").free
    except Exception:
        try:
            disk_free = psutil.disk_usage("/").free
        except Exception:
            disk_free = None

    return HealthInfo(
        gpu_temp_c=temp,
        gpu_util_pct=util,
        gpu_throttling=throttling,
        fan_state=fan_state,
        fan_rpm=fan_rpm,
        cpu_pct=cpu,
        ram_pct=ram,
        disk_free_bytes=disk_free,
        uptime_s=int(time.time() - _boot),
    )


def check_alerts(h: HealthInfo) -> list[dict]:
    alerts = []
    if h.gpu_temp_c is not None and h.gpu_temp_c > 80:
        alerts.append({"id": "gpu-temp", "severity": "critical",
                       "message": f"GPU temp {h.gpu_temp_c:.0f}°C exceeds 80°C",
                       "timestamp": utcnow()})
    if h.gpu_throttling:
        alerts.append({"id": "gpu-throttle", "severity": "warning",
                       "message": "GPU thermal throttling detected",
                       "timestamp": utcnow()})
    if h.fan_state == FanState.STOPPED:
        alerts.append({"id": "fan-stopped", "severity": "critical",
                       "message": "GPU fan reports stopped",
                       "timestamp": utcnow()})
    return alerts
