"""Thread pool executor manager for background tasks"""

from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Any, Optional
import logging
import atexit
import threading

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Centralized thread pool executor for background tasks"""

    _instance: Optional["TaskExecutor"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._executor = ThreadPoolExecutor(
            max_workers=8,
            thread_name_prefix="hiresti_worker",
        )
        self._initialized = True
        atexit.register(self.shutdown)
        logger.info("TaskExecutor initialized with max_workers=8")

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        """Submit a task to the thread pool"""
        return self._executor.submit(fn, *args, **kwargs)

    def submit_daemon(self, fn: Callable, *args, **kwargs) -> Future:
        """Submit a daemon task (runs in background)"""
        def wrapper():
            try:
                fn(*args, **kwargs)
            except Exception as e:
                logger.warning("TaskExecutor: task %s failed: %s", fn.__name__, e)
        return self._executor.submit(wrapper)

    def map(self, fn: Callable, *iterables, timeout=None, chunksize=1):
        """Map function over iterables"""
        return self._executor.map(fn, *iterables, timeout=timeout, chunksize=chunksize)

    def shutdown(self, wait: bool = True):
        """Shutdown the executor"""
        if self._instance is None:
            return
        logger.info("TaskExecutor shutting down")
        self._executor.shutdown(wait=wait)
        TaskExecutor._instance = None


def submit_task(fn: Callable, *args, **kwargs) -> Future:
    """Convenience function to submit a task"""
    return TaskExecutor().submit(fn, *args, **kwargs)


def submit_daemon(fn: Callable, *args, **kwargs) -> Future:
    """Convenience function to submit a daemon task"""
    return TaskExecutor().submit_daemon(fn, *args, **kwargs)
