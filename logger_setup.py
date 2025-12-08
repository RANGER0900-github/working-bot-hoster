"""
Logging configuration module for Bot Hoster.
Sets up comprehensive logging with file rotation and proper formatting.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from config import LOG_DIR, LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT

def setup_logging(log_level: int = logging.INFO) -> logging.Logger:
    """
    Set up logging configuration.
    
    Args:
        log_level: Logging level (default: INFO)
        
    Returns:
        logging.Logger: Configured root logger
    """
    # Create log directory if it doesn't exist
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)
    
    # Suppress noisy third-party loggers
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    
    root_logger.info("=" * 60)
    root_logger.info("Bot Hoster - Logging initialized")
    root_logger.info(f"Log file: {LOG_FILE}")
    root_logger.info(f"Log level: {logging.getLevelName(log_level)}")
    root_logger.info("=" * 60)
    
    return root_logger

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        logging.Logger: Logger instance
    """
    return logging.getLogger(name)

