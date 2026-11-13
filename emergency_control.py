"""Process-local emergency-stop coordinator for AgentFactory-owned workers.

Only processes explicitly registered here can be terminated. Remote API jobs and
unregistered/independent services are outside this coordinator's control.
"""
import os
import subprocess
import threading


class EmergencyStopped(RuntimeError):
    pass


class EmergencyController:
    def __init__(self):
        self._lock = threading.RLock()
        self._stopped = threading.Event()
        self._children = set()

    def check(self):
        if self._stopped.is_set():
            raise EmergencyStopped("Not-Aus aktiv: keine weiteren Aktionen erlaubt.")

    def register(self, process):
        """Register a subprocess.Popen instance immediately after creation."""
        with self._lock:
            self.check()
            if process.poll() is None:
                self._children.add(process)

    def unregister(self, process):
        with self._lock:
            self._children.discard(process)

    def stop(self):
        """Latch stop before touching children; never allow a restart in-process."""
        with self._lock:
            self._stopped.set()
            children = tuple(self._children)
            self._children.clear()
        for process in children:
            try:
                if process.poll() is not None:
                    continue
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                        check=False,
                    )
                else:
                    process.kill()
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except (OSError, subprocess.SubprocessError):
                    pass

    @property
    def stopped(self):
        return self._stopped.is_set()


emergency = EmergencyController()
