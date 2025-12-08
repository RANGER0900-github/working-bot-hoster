"""
Code execution module for Bot Hoster.
Handles execution of user code, process management, and console output monitoring.
"""
import asyncio
import subprocess
import logging
import time
import os
from pathlib import Path
from typing import List, Optional, Callable, Any, Tuple
import psutil

logger = logging.getLogger(__name__)

class CodeExecutor:
    """Handles code execution and process management."""
    
    def __init__(self, max_console_lines: int = 50, update_interval: int = 3):
        """
        Initialize CodeExecutor.
        
        Args:
            max_console_lines: Maximum number of console lines to keep
            update_interval: Interval in seconds between console updates
        """
        self.max_console_lines = max_console_lines
        self.update_interval = update_interval
        logger.info(f"CodeExecutor initialized with max_lines={max_console_lines}, update_interval={update_interval}")
    
    def start_process(self, script_path: Path, working_dir: Path, env: Optional[dict] = None) -> Tuple[subprocess.Popen, Optional[str]]:
        """
        Start a Python process.
        
        Args:
            script_path: Path to the Python script to execute
            working_dir: Working directory for the process
            env: Optional environment variables
            
        Returns:
            tuple: (process, error_message)
        """
        try:
            # Validate paths
            if not script_path.exists():
                error_msg = f"Script not found: {script_path}"
                logger.error(error_msg)
                return None, error_msg
            
            if not script_path.is_file():
                error_msg = f"Path is not a file: {script_path}"
                logger.error(error_msg)
                return None, error_msg
            
            # Security check: ensure script is within working directory
            try:
                script_path.resolve().relative_to(working_dir.resolve())
            except ValueError:
                error_msg = f"Script path is outside working directory: {script_path}"
                logger.error(error_msg)
                return None, error_msg
            
            logger.info(f"Starting process: {script_path} in {working_dir}")
            
            # Prepare environment
            process_env = os.environ.copy()
            if env:
                process_env.update(env)
            
            # Start process
            process = subprocess.Popen(
                ['python3', str(script_path)],
                cwd=str(working_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=process_env
            )
            
            logger.info(f"Process started with PID {process.pid}")
            return process, None
            
        except PermissionError:
            error_msg = f"Permission denied executing script: {script_path}"
            logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"Error starting process: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg
    
    async def monitor_console_output(
        self,
        process: subprocess.Popen,
        output_callback: Callable[[List[str]], Any],
        max_output_length: int = 1900
    ) -> List[str]:
        """
        Monitor console output from a process.
        
        Args:
            process: Subprocess object
            output_callback: Async callback function to call with output lines
            max_output_length: Maximum length of output to send in callback
            
        Returns:
            list: All output lines
        """
        output_lines = []
        last_update = 0
        
        try:
            logger.info(f"Starting console monitoring for PID {process.pid}")
            
            while True:
                # Check if process is still running
                if process.poll() is not None:
                    # Process ended, read remaining output
                    try:
                        remaining = process.stdout.read()
                        if remaining:
                            for line in remaining.split('\n'):
                                line = line.strip()
                                if line:
                                    output_lines.append(line)
                                    if len(output_lines) > self.max_console_lines:
                                        output_lines.pop(0)
                    except Exception as e:
                        logger.warning(f"Error reading remaining output: {str(e)}")
                    break
                
                # Read line
                try:
                    line = process.stdout.readline()
                    if not line:
                        await asyncio.sleep(0.5)
                        continue
                    
                    line = line.strip()
                    if line:
                        output_lines.append(line)
                        if len(output_lines) > self.max_console_lines:
                            output_lines.pop(0)
                        
                        # Update callback periodically
                        current_time = time.time()
                        if len(output_lines) % 3 == 0 or (current_time - last_update) > self.update_interval:
                            try:
                                output_text = "\n".join(output_lines[-20:])
                                if len(output_text) > max_output_length:
                                    output_text = output_text[-max_output_length:]
                                
                                await output_callback(output_lines[-20:])
                                last_update = current_time
                            except Exception as e:
                                logger.warning(f"Error in output callback: {str(e)}")
                
                except Exception as e:
                    logger.warning(f"Error reading console output: {str(e)}")
                    await asyncio.sleep(0.5)
            
            logger.info(f"Console monitoring ended for PID {process.pid}")
            return output_lines
            
        except Exception as e:
            error_msg = f"Error monitoring console output: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return output_lines
    
    def stop_process(self, process: subprocess.Popen, timeout: int = 5) -> Tuple[bool, Optional[str]]:
        """
        Stop a process gracefully, then forcefully if needed.
        
        Args:
            process: Subprocess object
            timeout: Timeout in seconds for graceful termination
            
        Returns:
            tuple: (success, error_message)
        """
        try:
            if process.poll() is not None:
                logger.info(f"Process {process.pid} already terminated")
                return True, None
            
            logger.info(f"Stopping process {process.pid}")
            
            # Try graceful termination
            try:
                process.terminate()
                process.wait(timeout=timeout)
                logger.info(f"Process {process.pid} stopped gracefully")
                return True, None
            except subprocess.TimeoutExpired:
                # Force kill if graceful termination fails
                logger.warning(f"Process {process.pid} did not terminate gracefully, force killing")
                try:
                    process.kill()
                    process.wait(timeout=2)
                    logger.info(f"Process {process.pid} force killed")
                    return True, None
                except Exception as e:
                    error_msg = f"Error force killing process: {str(e)}"
                    logger.error(error_msg)
                    return False, error_msg
            except Exception as e:
                error_msg = f"Error stopping process: {str(e)}"
                logger.error(error_msg, exc_info=True)
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Error stopping process: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def is_process_running(self, process: subprocess.Popen) -> bool:
        """
        Check if a process is still running.
        
        Args:
            process: Subprocess object
            
        Returns:
            bool: True if process is running
        """
        try:
            return process.poll() is None
        except Exception:
            return False
    
    def get_process_info(self, process: subprocess.Popen) -> Optional[dict]:
        """
        Get information about a running process.
        
        Args:
            process: Subprocess object
            
        Returns:
            dict: Process information or None
        """
        try:
            if process.poll() is not None:
                return None
            
            pid = process.pid
            proc = psutil.Process(pid)
            
            return {
                'pid': pid,
                'cpu_percent': proc.cpu_percent(interval=0.1),
                'memory_mb': proc.memory_info().rss / (1024 * 1024),
                'status': proc.status()
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.warning(f"Error getting process info: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error getting process info: {str(e)}", exc_info=True)
            return None

