import os
import time
import traceback
from threading import Lock
import json
from enum import Enum
from typing import Optional, Dict, Any

LOG_FILE_PATH = '/var/www/glkb/neo4j_agent/chatbot/logs'
LOG_ENABLED = True

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class Logger:
    def __init__(self):
        self.file_path = LOG_FILE_PATH
        os.makedirs(self.file_path, exist_ok=True)
        self.log_file = open(os.path.join(self.file_path, 'ai_agent.log'), 'a')
        self.log_file_lock = Lock()
        self.enabled = LOG_ENABLED
        self.start_time = time.time()

    def enable(self):
        """Enable logging and write start marker"""
        if not self.enabled:
            with self.log_file_lock:
                self.log_file.write(f'\n\n[Time: {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}] LOG START\n')
                self.log_file.flush()
        self.enabled = True

    def disable(self):
        """Disable logging"""
        self.enabled = False

    def _format_log_entry(self, level: LogLevel, event_type: str, data: Dict[str, Any], 
                         duration: Optional[float] = None, error: Optional[Exception] = None) -> str:
        """Format a log entry with enhanced structure"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        elapsed = time.time() - self.start_time
        
        # Base log data
        log_data = {
            "timestamp": timestamp,
            "level": level.value,
            "event_type": event_type,
            "elapsed_seconds": round(elapsed, 3),
            "data": data
        }
        
        # Add duration if provided
        if duration is not None:
            log_data["duration_seconds"] = round(duration, 3)
        
        # Add error information if provided
        if error is not None:
            log_data["error"] = {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc()
            }
        
        return json.dumps(log_data, indent=2, ensure_ascii=False)

    def log(self, event_type: str, data: Dict[str, Any], level: LogLevel = LogLevel.INFO, 
            duration: Optional[float] = None, error: Optional[Exception] = None):
        """Log an event with timestamp, level, and structured data"""
        if not self.enabled:
            return

        with self.log_file_lock:
            log_entry = self._format_log_entry(level, event_type, data, duration, error)
            self.log_file.write(f'{log_entry}\n\n')
            self.log_file.flush()

    def debug(self, event_type: str, data: Dict[str, Any], duration: Optional[float] = None):
        """Log a debug message"""
        self.log(event_type, data, LogLevel.DEBUG, duration)

    def info(self, event_type: str, data: Dict[str, Any], duration: Optional[float] = None):
        """Log an info message"""
        self.log(event_type, data, LogLevel.INFO, duration)

    def warning(self, event_type: str, data: Dict[str, Any], duration: Optional[float] = None):
        """Log a warning message"""
        self.log(event_type, data, LogLevel.WARNING, duration)

    def error(self, event_type: str, data: Dict[str, Any], error: Optional[Exception] = None, 
              duration: Optional[float] = None):
        """Log an error message with optional exception details"""
        self.log(event_type, data, LogLevel.ERROR, duration, error)

    def critical(self, event_type: str, data: Dict[str, Any], error: Optional[Exception] = None, 
                 duration: Optional[float] = None):
        """Log a critical message with optional exception details"""
        self.log(event_type, data, LogLevel.CRITICAL, duration, error)

    def log_step_start(self, step_name: str, step_data: Dict[str, Any] = None):
        """Log the start of a processing step"""
        data = {"step": step_name, "status": "started"}
        if step_data:
            data.update(step_data)
        self.info("STEP_START", data)

    def log_step_end(self, step_name: str, step_data: Dict[str, Any] = None, 
                     duration: Optional[float] = None, success: bool = True):
        """Log the end of a processing step"""
        data = {"step": step_name, "status": "completed" if success else "failed"}
        if step_data:
            data.update(step_data)
        level = LogLevel.INFO if success else LogLevel.ERROR
        self.log("STEP_END", data, level, duration)

    def log_performance(self, operation: str, metrics: Dict[str, Any]):
        """Log performance metrics for an operation"""
        self.info("PERFORMANCE", {"operation": operation, "metrics": metrics})

    def __del__(self):
        """Ensure log file is closed when logger is destroyed"""
        self.log_file.close()

# Create singleton instance
logger = Logger()

def get_logger():
    """Get the singleton logger instance"""
    return logger