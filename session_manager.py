"""
Session management module for Bot Hoster.
Manages user sessions, running bots, and project state.
"""
import logging
import time
from typing import Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

logger = logging.getLogger(__name__)

class SessionManager:
    """Manages user sessions and running bot processes."""
    
    def __init__(self, session_timeout: int = 600):
        """
        Initialize SessionManager.
        
        Args:
            session_timeout: Session timeout in seconds (default: 10 minutes)
        """
        self.session_timeout = session_timeout
        self.running_bots: Dict[int, Dict[str, Any]] = {}  # {user_id: {process, project_path, console_output, message, start_time}}
        self.user_projects: Dict[int, str] = {}  # {user_id: upload_location}
        self.user_sessions: Dict[int, Dict[str, Any]] = {}  # {user_id: {last_activity, upload_location, ...}}
        logger.info(f"SessionManager initialized with timeout={session_timeout}")
    
    def start_upload_session(self, user_id: int, upload_location: str) -> bool:
        """
        Start an upload session for a user.
        
        Args:
            user_id: Discord user ID
            upload_location: "channel" or "dm"
            
        Returns:
            bool: True if session started successfully
        """
        try:
            self.user_projects[user_id] = upload_location
            self.user_sessions[user_id] = {
                'last_activity': datetime.now(),
                'upload_location': upload_location,
                'state': 'uploading'
            }
            logger.info(f"Started upload session for user {user_id} in {upload_location}")
            return True
        except Exception as e:
            logger.error(f"Error starting upload session for user {user_id}: {str(e)}", exc_info=True)
            return False
    
    def end_upload_session(self, user_id: int) -> bool:
        """
        End an upload session for a user.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            bool: True if session ended successfully
        """
        try:
            if user_id in self.user_projects:
                del self.user_projects[user_id]
            if user_id in self.user_sessions:
                del self.user_sessions[user_id]
            logger.info(f"Ended upload session for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error ending upload session for user {user_id}: {str(e)}", exc_info=True)
            return False
    
    def get_upload_location(self, user_id: int) -> Optional[str]:
        """
        Get upload location for a user.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            str: "channel", "dm", or None
        """
        return self.user_projects.get(user_id)
    
    def is_user_uploading(self, user_id: int) -> bool:
        """
        Check if user is in upload process.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            bool: True if user is uploading
        """
        return user_id in self.user_projects
    
    def register_running_bot(self, user_id: int, process: subprocess.Popen, project_path: Path, message) -> bool:
        """
        Register a running bot process.
        
        Args:
            user_id: Discord user ID
            process: Subprocess object
            project_path: Path to project directory
            message: Discord message object
            
        Returns:
            bool: True if registered successfully
        """
        try:
            self.running_bots[user_id] = {
                'process': process,
                'project_path': str(project_path),
                'console_output': [],
                'message': message,
                'start_time': datetime.now()
            }
            logger.info(f"Registered running bot for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error registering bot for user {user_id}: {str(e)}", exc_info=True)
            return False
    
    def stop_bot(self, user_id: int, timeout: int = 5) -> Tuple[bool, Optional[str]]:
        """
        Stop a running bot process.
        
        Args:
            user_id: Discord user ID
            timeout: Timeout in seconds for graceful termination
            
        Returns:
            tuple: (success, error_message)
        """
        try:
            if user_id not in self.running_bots:
                logger.warning(f"No running bot found for user {user_id}")
                return False, "No bot is running"
            
            bot_info = self.running_bots[user_id]
            process = bot_info.get('process')
            
            if not process:
                logger.warning(f"No process found for user {user_id}")
                del self.running_bots[user_id]
                return False, "No process found"
            
            # Try graceful termination
            try:
                process.terminate()
                process.wait(timeout=timeout)
                logger.info(f"Bot stopped gracefully for user {user_id}")
            except subprocess.TimeoutExpired:
                # Force kill if graceful termination fails
                try:
                    process.kill()
                    process.wait(timeout=2)
                    logger.warning(f"Bot force-killed for user {user_id}")
                except Exception as e:
                    logger.error(f"Error force-killing bot for user {user_id}: {str(e)}", exc_info=True)
            except Exception as e:
                logger.error(f"Error stopping bot for user {user_id}: {str(e)}", exc_info=True)
                try:
                    process.kill()
                except:
                    pass
            
            del self.running_bots[user_id]
            return True, None
            
        except Exception as e:
            error_msg = f"Error stopping bot: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def get_running_bot(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Get running bot info for a user.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            dict: Bot info or None
        """
        return self.running_bots.get(user_id)
    
    def is_bot_running(self, user_id: int) -> bool:
        """
        Check if user has a running bot.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            bool: True if bot is running
        """
        if user_id not in self.running_bots:
            return False
        
        bot_info = self.running_bots[user_id]
        process = bot_info.get('process')
        
        if not process:
            return False
        
        # Check if process is still running
        return process.poll() is None
    
    def get_running_bots_count(self) -> int:
        """
        Get count of currently running bots.
        
        Returns:
            int: Number of running bots
        """
        count = 0
        for user_id, bot_info in list(self.running_bots.items()):
            process = bot_info.get('process')
            if process and process.poll() is None:
                count += 1
            else:
                # Clean up dead processes
                try:
                    del self.running_bots[user_id]
                except:
                    pass
        return count
    
    def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions.
        
        Returns:
            int: Number of sessions cleaned up
        """
        cleaned = 0
        now = datetime.now()
        
        for user_id, session in list(self.user_sessions.items()):
            last_activity = session.get('last_activity')
            if last_activity and (now - last_activity) > timedelta(seconds=self.session_timeout):
                try:
                    # Do NOT stop running bots here — running bots should remain active 24x7.
                    # Only remove session metadata (upload/session state) while preserving running processes.
                    del self.user_sessions[user_id]
                    if user_id in self.user_projects:
                        del self.user_projects[user_id]

                    cleaned += 1
                    logger.info(f"Cleaned up expired session metadata for user {user_id} (bot preserved if running)")
                except Exception as e:
                    logger.error(f"Error cleaning up session for user {user_id}: {str(e)}", exc_info=True)
        
        return cleaned
    
    def update_activity(self, user_id: int) -> None:
        """
        Update last activity time for a user.
        
        Args:
            user_id: Discord user ID
        """
        if user_id in self.user_sessions:
            self.user_sessions[user_id]['last_activity'] = datetime.now()

