"""Local process measurements; hosted model CPU/GPU and monetary costs are unknown."""

import platform
import threading
import time


def machine_info():
    info = {"python": platform.python_version(), "platform": platform.platform(),
            "architecture": platform.machine()}
    try:
        import psutil
        info.update(logical_cpus=psutil.cpu_count(), physical_cpus=psutil.cpu_count(logical=False),
                    ram_mb=round(psutil.virtual_memory().total / 1024**2, 2))
    except (ImportError, OSError):
        pass
    return info


class ProcessMeasurement:
    """CPU time delta and sampled process RSS during one pipeline invocation."""
    def __init__(self, interval=0.1):
        if interval <= 0:
            raise ValueError("Memory sampling interval must be positive")
        self.interval = interval
        self.metrics = {}
        self.samples = []
        self.stop = threading.Event()
        self.thread = None
        self.memory_error = None
        try:
            import psutil
            self.process = psutil.Process()
        except (ImportError, OSError) as error:
            self.process = None
            self.memory_error = str(error)

    def sample(self):
        if self.process is None:
            return
        try:
            self.samples.append(self.process.memory_info().rss / 1024**2)
        except Exception as error:
            self.memory_error = str(error)
            self.process = None

    def monitor(self):
        while not self.stop.wait(self.interval):
            self.sample()

    def __enter__(self):
        self.cpu_start = time.process_time()
        if self.process is not None:
            self.sample()
            self.thread = threading.Thread(target=self.monitor, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            self.thread.join()
            self.sample()
        self.metrics = {"local_cpu_seconds": round(time.process_time() - self.cpu_start, 6),
                        "local_rss_start_mb": self.samples[0] if self.samples else None,
                        "local_rss_peak_mb": max(self.samples) if self.samples else None,
                        "local_rss_end_mb": self.samples[-1] if self.samples else None,
                        "local_rss_delta_mb": self.samples[-1] - self.samples[0] if self.samples else None,
                        "local_rss_samples": len(self.samples),
                        "local_memory_error": self.memory_error}
