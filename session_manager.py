"""
Session management module for Bot Hoster.
Manages user sessions, running bots, and project state.
"""
import logging
from typing import Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import json
import time

from config import MAX_BOTS_PER_USER, get_user_project_dir, get_user_root_dir

logger = logging.getLogger(__name__)

# region agent log helper
DEBUG_LOG_PATH = Path("/home/kali/Downloads/working-bot-hoster/.cursor/debug.log")


def _agent_debug_log(hypothesis_id: str, location: str, message: str, data: Dict):
    """Append a single NDJSON debug log line for debug-mode analysis."""
    try:
        payload = {
            "sessionId": "debug-session",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass
# endregion


class SessionManager:
    """Manages user sessions and running bot processes (multi-bot aware)."""
    
    def __init__(self, session_timeout: int = 600):
        """
        Initialize SessionManager.
        
        Args:
            session_timeout: Session timeout in seconds (default: 10 minutes)
        """
        self.session_timeout = session_timeout
        # running_bots: {user_id: {slot: {process, project_path, console_output, message, start_time}}}
        self.running_bots: Dict[int, Dict[int, Dict[str, Any]]] = {}
        # user_projects: {user_id: {"upload_location": str, "slot": int, "project_path": str}}
        self.user_projects: Dict[int, Dict[str, Any]] = {}
        # user_sessions: {user_id: {last_activity, upload_location, state, slot}}
        self.user_sessions: Dict[int, Dict[str, Any]] = {}
        logger.info(f"SessionManager initialized with timeout={session_timeout}, max_bots={MAX_BOTS_PER_USER}")
    
    # -------- Upload session handling -------- #
    def _get_available_slot(self, user_id: int) -> Optional[int]:
        """Return the first available slot for a user."""
        occupied = set()
        if user_id in self.running_bots:
            occupied.update(self.running_bots[user_id].keys())
        # If an upload session is active, reserve its slot
        if user_id in self.user_projects and "slot" in self.user_projects[user_id]:
            occupied.add(self.user_projects[user_id]["slot"])
        for slot in range(1, MAX_BOTS_PER_USER + 1):
            if slot not in occupied:
                return slot
        return None
    
    def start_upload_session(self, user_id: int, upload_location: str) -> Tuple[bool, Optional[str], Optional[int], Optional[Path]]:
        """
        Start an upload session for a user.
        
        Args:
            user_id: Discord user ID
            upload_location: "channel" or "dm"
            
        Returns:
            tuple: (success, error_message, slot, project_path)
        """
        try:
            slot = self._get_available_slot(user_id)
            if slot is None:
                error_msg = f"Maximum bots ({MAX_BOTS_PER_USER}) already running or reserved."
                logger.warning(error_msg)
                # region agent log
                _agent_debug_log(
                    "HYP_A",
                    "session_manager.py:start_upload_session:no_slot",
                    "No available slot when starting upload session",
                    {"user_id": user_id, "max_bots": MAX_BOTS_PER_USER},
                )
                # endregion
                return False, error_msg, None, None
            
            project_path = get_user_project_dir(user_id, slot)
            self.user_projects[user_id] = {
                "upload_location": upload_location,
                "slot": slot,
                "project_path": str(project_path)
            }
            self.user_sessions[user_id] = {
                'last_activity': datetime.now(),
                'upload_location': upload_location,
                'state': 'uploading',
                'slot': slot
            }
            logger.info(f"Started upload session for user {user_id} in {upload_location} (slot {slot})")
            # region agent log
            _agent_debug_log(
                "HYP_A",
                "session_manager.py:start_upload_session:success",
                "Started upload session",
                {"user_id": user_id, "slot": slot, "location": upload_location},
            )
            # endregion
            return True, None, slot, project_path
        except Exception as e:
            logger.error(f"Error starting upload session for user {user_id}: {str(e)}", exc_info=True)
            return False, str(e), None, None
    
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
        """Get upload location for a user."""
        return self.user_projects.get(user_id, {}).get("upload_location")
    
    def get_upload_slot(self, user_id: int) -> Optional[int]:
        """Return the slot reserved for current upload session."""
        return self.user_projects.get(user_id, {}).get("slot")
    
    def get_upload_project_dir(self, user_id: int) -> Optional[Path]:
        """Return the project directory for the current upload session."""
        project_path = self.user_projects.get(user_id, {}).get("project_path")
        return Path(project_path) if project_path else None
    
    def is_user_uploading(self, user_id: int) -> bool:
        """Check if user is in upload process."""
        return user_id in self.user_projects
    
    # -------- Running bot tracking -------- #
    def register_running_bot(self, user_id: int, slot: int, process: subprocess.Popen, project_path: Path, message) -> bool:
        """
        Register a running bot process.
        
        Args:
            user_id: Discord user ID
            slot: Slot number
            process: Subprocess object
            project_path: Path to project directory
            message: Discord message object
            
        Returns:
            bool: True if registered successfully
        """
        try:
            if user_id not in self.running_bots:
                self.running_bots[user_id] = {}
            self.running_bots[user_id][slot] = {
                'process': process,
                'project_path': str(project_path),
                'console_output': [],
                'message': message,
                'start_time': datetime.now()
            }
            logger.info(f"Registered running bot for user {user_id} in slot {slot}")
            return True
        except Exception as e:
            logger.error(f"Error registering bot for user {user_id} slot {slot}: {str(e)}", exc_info=True)
            return False
    
    def stop_bot(self, user_id: int, slot: Optional[int] = None, timeout: int = 5) -> Tuple[bool, Optional[str]]:
        """
        Stop a running bot process.
        
        Args:
            user_id: Discord user ID
            slot: Slot number to stop (None = stop all)
            timeout: Timeout in seconds for graceful termination
            
        Returns:
            tuple: (success, error_message)
        """
        try:
            if user_id not in self.running_bots:
                logger.warning(f"No running bot found for user {user_id}")
                return False, "No bot is running"
            
            slots = [slot] if slot else list(self.running_bots[user_id].keys())
            for s in slots:
                bot_info = self.running_bots[user_id].get(s)
                if not bot_info:
                    continue
                process = bot_info.get('process')
                
                if not process:
                    logger.warning(f"No process found for user {user_id} slot {s}")
                    try:
                        del self.running_bots[user_id][s]
                    except Exception:
                        pass
                    continue
                
                # Try graceful termination
                try:
                    process.terminate()
                    process.wait(timeout=timeout)
                    logger.info(f"Bot stopped gracefully for user {user_id} slot {s}")
                except subprocess.TimeoutExpired:
                    # Force kill if graceful termination fails
                    try:
                        process.kill()
                        process.wait(timeout=2)
                        logger.warning(f"Bot force-killed for user {user_id} slot {s}")
                    except Exception as e:
                        logger.error(f"Error force-killing bot for user {user_id} slot {s}: {str(e)}", exc_info=True)
                except Exception as e:
                    logger.error(f"Error stopping bot for user {user_id} slot {s}: {str(e)}", exc_info=True)
                    try:
                        process.kill()
                    except Exception:
                        pass
                
                try:
                    del self.running_bots[user_id][s]
                except Exception:
                    pass
            
            if user_id in self.running_bots and not self.running_bots[user_id]:
                del self.running_bots[user_id]
            return True, None
            
        except Exception as e:
            error_msg = f"Error stopping bot: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def get_running_bot(self, user_id: int, slot: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Get running bot info for a user (optionally by slot).
        """
        if user_id not in self.running_bots:
            return None
        if slot is None:
            # Return first available
            return next(iter(self.running_bots[user_id].values()), None)
        return self.running_bots[user_id].get(slot)
    
    def is_bot_running(self, user_id: int, slot: Optional[int] = None) -> bool:
        """
        Check if user has a running bot (optionally in a specific slot).
        """
        if user_id not in self.running_bots:
            return False
        
        if slot is None:
            for bot_info in self.running_bots[user_id].values():
                process = bot_info.get('process')
                if process and process.poll() is None:
                    return True
            return False
        
        bot_info = self.running_bots[user_id].get(slot)
        if not bot_info:
            return False
        process = bot_info.get('process')
        if not process:
            return False
        return process.poll() is None
    
    def get_running_bots_count(self) -> int:
        """
        Get count of currently running bots across all users.
        """
        count = 0
        for user_id, slots in list(self.running_bots.items()):
            for slot, bot_info in list(slots.items()):
                process = bot_info.get('process')
                if process and process.poll() is None:
                    count += 1
                else:
                    try:
                        del self.running_bots[user_id][slot]
                    except Exception:
                        pass
            if user_id in self.running_bots and not self.running_bots[user_id]:
                try:
                    del self.running_bots[user_id]
                except Exception:
                    pass
        return count
    
    def get_running_bots_count_for_user(self, user_id: int) -> int:
        """Return the number of running bots for a specific user."""
        if user_id not in self.running_bots:
            return 0
        return sum(1 for b in self.running_bots[user_id].values() if b.get('process') and b['process'].poll() is None)
    
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
        """Update last activity time for a user."""
        if user_id in self.user_sessions:
            self.user_sessions[user_id]['last_activity'] = datetime.now()
    
    # -------- Utility helpers -------- #
    def ensure_user_root(self, user_id: int) -> Path:
        """Ensure root directory exists for a user."""
        return get_user_root_dir(user_id)

