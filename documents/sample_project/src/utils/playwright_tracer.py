"""
Playwright Tracing utility for CRM automation.
Provides comprehensive tracing functionality to capture all browser interactions
and save them to request-specific directories for debugging and analysis.
"""

import logging
from pathlib import Path
from typing import Optional
from playwright.async_api import BrowserContext, Page


class PlaywrightTracer:
    """Manages Playwright tracing for CRM automation sessions."""
    
    def __init__(self, run_id: str, logger: logging.Logger):
        """
        Initialize the tracer.
        
        Args:
            run_id: The run identifier (e.g., "run_2025-12-19/bot_1-req_6939000")
            logger: Logger instance for logging trace operations
        """
        self.run_id = run_id
        self.logger = logger
        self._trace_dir: Optional[Path] = None
        self._trace_file: Optional[Path] = None
        self._is_tracing = False
        self._context: Optional[BrowserContext] = None
        
    def _setup_trace_directory(self) -> Path:
        """Setup the trace directory structure."""
        # Base logs directory
        base_logs = Path("data/logs")
        
        # Create trace_log folder in the specific request directory
        trace_dir = base_logs / self.run_id / "trace_log"
        trace_dir.mkdir(parents=True, exist_ok=True)
        
        # Create trace_screenshots subfolder
        screenshots_dir = trace_dir / "trace_screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"Created trace directory: {trace_dir}")
        self.logger.info(f"Created trace screenshots directory: {screenshots_dir}")
        return trace_dir
    
    async def start_tracing(self, context: BrowserContext, 
                          screenshots: bool = True, 
                          snapshots: bool = True,
                          sources: bool = True,
                          title: str = "CRM_Automation_Trace") -> None:
        """
        Start Playwright tracing with comprehensive options.
        
        Args:
            context: The browser context to trace
            screenshots: Whether to capture screenshots
            snapshots: Whether to capture DOM snapshots
            sources: Whether to capture source files
            title: Title for the trace
        """
        try:
            if self._is_tracing:
                self.logger.warning("Tracing is already started")
                return
                
            self._context = context
            self._trace_dir = self._setup_trace_directory()
            self._trace_file = self._trace_dir / f"{title.replace(' ', '_')}.zip"
            
            # Start tracing with comprehensive options
            await context.tracing.start(
                screenshots=screenshots,
                snapshots=snapshots,
                sources=sources,
                title=title
            )
            
            self._is_tracing = True
            self.logger.info(f"Started Playwright tracing: {self._trace_file}")
            
        except Exception as e:
            self.logger.error(f"Failed to start Playwright tracing: {e}")
            raise
    
    async def stop_tracing(self) -> Optional[Path]:
        """
        Stop tracing and save the trace file.
        
        Returns:
            Path to the saved trace file, or None if tracing wasn't active
        """
        try:
            if not self._is_tracing or not self._context:
                self.logger.warning("Tracing is not active")
                return None
                
            # Stop and save the trace
            await self._context.tracing.stop(path=str(self._trace_file))
            self._is_tracing = False
            
            self.logger.info(f"Stopped tracing and saved to: {self._trace_file}")
            self.logger.info(f"To view trace: playwright show-trace {self._trace_file}")
            
            return self._trace_file
            
        except Exception as e:
            self.logger.error(f"Failed to stop Playwright tracing: {e}")
            self._is_tracing = False
            return None
    
    async def capture_trace_screenshot(self, page: Page, name: str = "trace_screenshot") -> Optional[Path]:
        """
        Capture a screenshot during tracing for additional context.
        
        Args:
            page: The page to screenshot
            name: Name for the screenshot file
            
        Returns:
            Path to the saved screenshot, or None if failed
        """
        try:
            if not self._trace_dir:
                self._trace_dir = self._setup_trace_directory()
                
            # Save screenshots in the trace_screenshots subfolder
            screenshots_dir = self._trace_dir / "trace_screenshots"
            screenshot_path = screenshots_dir / f"{name}.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            
            self.logger.info(f"Captured trace screenshot: {screenshot_path}")
            return screenshot_path
            
        except Exception as e:
            self.logger.error(f"Failed to capture trace screenshot: {e}")
            return None
    
    def get_trace_info(self) -> dict:
        """
        Get information about the current trace.
        
        Returns:
            Dictionary with trace information
        """
        return {
            "is_tracing": self._is_tracing,
            "run_id": self.run_id,
            "trace_dir": str(self._trace_dir) if self._trace_dir else None,
            "trace_file": str(self._trace_file) if self._trace_file else None,
        }
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - ensure tracing is stopped."""
        if self._is_tracing:
            await self.stop_tracing()


# Convenience functions for easy integration

async def setup_tracing_context(context: BrowserContext, 
                               run_id: str, 
                               logger: logging.Logger,
                               title: str = "CRM_Automation_Trace") -> PlaywrightTracer:
    """
    Convenience function to setup tracing on a browser context.
    
    Args:
        context: Browser context to enable tracing on
        run_id: Run identifier for organizing traces
        logger: Logger instance
        title: Title for the trace
        
    Returns:
        Configured PlaywrightTracer instance
    """
    tracer = PlaywrightTracer(run_id, logger)
    await tracer.start_tracing(context, title=title)
    return tracer


def get_trace_viewer_command(trace_file: Path) -> str:
    """
    Get the command to view a trace file with Playwright Trace Viewer.
    
    Args:
        trace_file: Path to the trace file
        
    Returns:
        Command string to execute
    """
    return f"playwright show-trace {trace_file}"