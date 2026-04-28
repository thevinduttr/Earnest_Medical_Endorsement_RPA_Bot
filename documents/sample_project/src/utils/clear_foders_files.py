import os
import shutil
from pathlib import Path
import logging
from typing import Optional

def clear_attachments_folder(logger: Optional[logging.Logger] = None) -> bool:
    """
    Clear all files and subdirectories in the data/attachments folder.
    
    Args:
        logger: Optional logger instance for logging operations
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        attachments_path = Path("data/attachments")
        
        if not attachments_path.exists():
            if logger:
                logger.info("Attachments folder does not exist, nothing to clear")
            return True
        
        # Count files and folders before clearing
        file_count = 0
        folder_count = 0
        
        for item in attachments_path.iterdir():
            if item.is_file():
                file_count += 1
            elif item.is_dir():
                folder_count += 1
        
        if file_count == 0 and folder_count == 0:
            if logger:
                logger.info("Attachments folder is already empty")
            return True
        
        # Clear all contents
        for item in attachments_path.iterdir():
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                if logger:
                    logger.error(f"Failed to delete {item}: {e}")
                return False
        
        if logger:
            logger.info(f"Successfully cleared attachments folder: {file_count} files and {folder_count} folders removed")
        
        return True
        
    except Exception as e:
        if logger:
            logger.error(f"Error clearing attachments folder: {e}")
        else:
            print(f"Error clearing attachments folder: {e}")
        return False

def clear_folder(folder_path: str, logger: Optional[logging.Logger] = None) -> bool:
    """
    Clear all files and subdirectories in a specified folder.
    
    Args:
        folder_path: Path to the folder to clear
        logger: Optional logger instance for logging operations
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        path = Path(folder_path)
        
        if not path.exists():
            if logger:
                logger.info(f"Folder {folder_path} does not exist, nothing to clear")
            return True
        
        # Count items before clearing
        file_count = 0
        folder_count = 0
        
        for item in path.iterdir():
            if item.is_file():
                file_count += 1
            elif item.is_dir():
                folder_count += 1
        
        if file_count == 0 and folder_count == 0:
            if logger:
                logger.info(f"Folder {folder_path} is already empty")
            return True
        
        # Clear all contents
        for item in path.iterdir():
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                if logger:
                    logger.error(f"Failed to delete {item}: {e}")
                return False
        
        if logger:
            logger.info(f"Successfully cleared folder {folder_path}: {file_count} files and {folder_count} folders removed")
        
        return True
        
    except Exception as e:
        if logger:
            logger.error(f"Error clearing folder {folder_path}: {e}")
        else:
            print(f"Error clearing folder {folder_path}: {e}")
        return False
