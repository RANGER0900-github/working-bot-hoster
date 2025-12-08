"""
File handling module for Bot Hoster.
Handles file operations including zip extraction, file reading, and file management.
"""
import os
import zipfile
import shutil
import logging
from pathlib import Path
from typing import List, Optional, Tuple
import aiofiles

logger = logging.getLogger(__name__)

class FileHandler:
    """Handles file operations for the bot hosting service."""
    
    def __init__(self, max_file_size: int = 100 * 1024):
        """
        Initialize FileHandler.
        
        Args:
            max_file_size: Maximum file size for reading (default: 100KB)
        """
        self.max_file_size = max_file_size
        logger.info(f"FileHandler initialized with max_file_size={max_file_size}")
    
    async def download_attachment(self, attachment, save_path: Path) -> Tuple[bool, Optional[str]]:
        """
        Download a Discord attachment to a file.
        
        Args:
            attachment: Discord attachment object
            save_path: Path where to save the file
            
        Returns:
            tuple: (success, error_message)
        """
        try:
            logger.info(f"Downloading attachment {attachment.filename} to {save_path}")
            data = await attachment.read()
            
            # Check file size
            if len(data) > 50 * 1024 * 1024:  # 50MB limit
                error_msg = f"File size ({len(data)} bytes) exceeds 50MB limit"
                logger.warning(error_msg)
                return False, error_msg
            
            save_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(save_path, 'wb') as f:
                await f.write(data)
            
            logger.info(f"Successfully downloaded {attachment.filename}")
            return True, None
            
        except Exception as e:
            error_msg = f"Error downloading attachment: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def extract_zip(self, zip_path: Path, extract_to: Path) -> Tuple[bool, Optional[str], List[str]]:
        """
        Extract a zip file to a directory.
        
        Args:
            zip_path: Path to the zip file
            extract_to: Directory to extract to
            
        Returns:
            tuple: (success, error_message, list_of_extracted_files)
        """
        try:
            logger.info(f"Extracting {zip_path} to {extract_to}")
            
            if not zip_path.exists():
                error_msg = f"Zip file not found: {zip_path}"
                logger.error(error_msg)
                return False, error_msg, []
            
            # Validate zip file
            if not zipfile.is_zipfile(zip_path):
                error_msg = "Invalid zip file format"
                logger.error(error_msg)
                return False, error_msg, []
            
            # Create extraction directory
            extract_to.mkdir(parents=True, exist_ok=True)
            
            # Extract files
            extracted_files = []
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Check for zip bombs (too many files or paths that escape)
                file_list = zip_ref.namelist()
                if len(file_list) > 10000:
                    error_msg = "Zip file contains too many files (potential zip bomb)"
                    logger.warning(error_msg)
                    return False, error_msg, []
                
                # Check for path traversal
                for file_path in file_list:
                    if os.path.isabs(file_path) or '..' in file_path:
                        error_msg = f"Invalid file path in zip: {file_path}"
                        logger.warning(error_msg)
                        return False, error_msg, []
                
                zip_ref.extractall(extract_to)
                extracted_files = file_list
            
            # Get all extracted files
            all_files = []
            for root, dirs, files in os.walk(extract_to):
                for file in files:
                    rel_path = os.path.relpath(os.path.join(root, file), extract_to)
                    all_files.append(rel_path)
            
            logger.info(f"Successfully extracted {len(all_files)} files")
            return True, None, all_files
            
        except zipfile.BadZipFile:
            error_msg = "Corrupted or invalid zip file"
            logger.error(error_msg)
            return False, error_msg, []
        except Exception as e:
            error_msg = f"Error extracting zip file: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg, []
    
    def read_file_safe(self, file_path: Path, max_size: Optional[int] = None) -> str:
        """
        Safely read file content with size limit.
        
        Args:
            file_path: Path to the file
            max_size: Maximum file size to read (uses instance default if None)
            
        Returns:
            str: File content or error message
        """
        try:
            max_size = max_size or self.max_file_size
            
            if not file_path.exists():
                error_msg = f"File not found: {file_path}"
                logger.warning(error_msg)
                return f"[Error: File not found]"
            
            file_size = file_path.stat().st_size
            if file_size > max_size:
                error_msg = f"File too large: {file_size} bytes (max: {max_size})"
                logger.warning(error_msg)
                return f"[File too large: {file_size} bytes]"
            
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            logger.debug(f"Successfully read file {file_path} ({len(content)} bytes)")
            return content
            
        except PermissionError:
            error_msg = f"Permission denied reading file: {file_path}"
            logger.error(error_msg)
            return f"[Error: Permission denied]"
        except Exception as e:
            error_msg = f"Error reading file {file_path}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return f"[Error reading file: {str(e)}]"
    
    def find_python_files(self, directory: Path) -> List[str]:
        """
        Find all Python files in a directory.
        
        Args:
            directory: Directory to search
            
        Returns:
            list: List of relative file paths
        """
        try:
            python_files = []
            for root, dirs, files in os.walk(directory):
                for file in files:
                    if file.endswith('.py'):
                        rel_path = os.path.relpath(os.path.join(root, file), directory)
                        python_files.append(rel_path)
            
            logger.debug(f"Found {len(python_files)} Python files in {directory}")
            return python_files
            
        except Exception as e:
            error_msg = f"Error finding Python files: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return []
    
    def find_requirements_file(self, directory: Path) -> Optional[Path]:
        """
        Find requirements.txt file in directory.
        
        Args:
            directory: Directory to search
            
        Returns:
            Path to requirements file or None
        """
        try:
            for req_file in ['requirements.txt', 'requirement.txt']:
                req_path = directory / req_file
                if req_path.exists() and req_path.is_file():
                    logger.info(f"Found requirements file: {req_path}")
                    return req_path
            
            logger.debug(f"No requirements file found in {directory}")
            return None
            
        except Exception as e:
            error_msg = f"Error finding requirements file: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return None
    
    def cleanup_directory(self, directory: Path) -> Tuple[bool, Optional[str]]:
        """
        Recursively delete a directory and all its contents.
        
        Args:
            directory: Directory to delete
            
        Returns:
            tuple: (success, error_message)
        """
        try:
            if not directory.exists():
                logger.debug(f"Directory does not exist: {directory}")
                return True, None
            
            logger.info(f"Cleaning up directory: {directory}")
            shutil.rmtree(directory)
            logger.info(f"Successfully deleted directory: {directory}")
            return True, None
            
        except PermissionError:
            error_msg = f"Permission denied deleting directory: {directory}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Error deleting directory {directory}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def get_all_files(self, directory: Path) -> List[str]:
        """
        Get all files in a directory recursively.
        
        Args:
            directory: Directory to scan
            
        Returns:
            list: List of relative file paths
        """
        try:
            all_files = []
            for root, dirs, files in os.walk(directory):
                for file in files:
                    rel_path = os.path.relpath(os.path.join(root, file), directory)
                    all_files.append(rel_path)
            
            logger.debug(f"Found {len(all_files)} files in {directory}")
            return all_files
            
        except Exception as e:
            error_msg = f"Error getting files from {directory}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return []

