"""Performance metrics collection."""
import time
from typing import Dict, Optional
from contextlib import asynccontextmanager
from .types import ProcessMetrics, LoggerProtocol


class MetricsCollector:
    def __init__(self, logger: LoggerProtocol):
        self.logger = logger
        self.metrics: Dict[str, ProcessMetrics] = {}
    
    @asynccontextmanager
    async def measure(self, process_name: str):
        start_time = time.time()
        error_count = 0
        success = True
        
        try:
            yield self
            self.logger.info(f"{process_name} started")
        except Exception as e:
            success = False
            error_count = 1
            self.logger.error(f"{process_name} failed: {e}")
            raise
        finally:
            end_time = time.time()
            duration = end_time - start_time
            
            self.metrics[process_name] = {
                'start_time': start_time,
                'end_time': end_time,
                'duration': duration,
                'success': success,
                'error_count': error_count
            }
            
            status = "completed" if success else "failed"
            self.logger.info(f"{process_name} {status} in {duration:.2f}s")
    
    def get_metrics(self, process_name: str) -> Optional[ProcessMetrics]:
        return self.metrics.get(process_name)