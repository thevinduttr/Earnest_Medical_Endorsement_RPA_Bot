"""
Attachment management utilities for downloading documents from Azure Blob Storage
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

from src.services.db_service.data_service import DataService
from src.services.blob_service.blob_download_service import BlobDownloadService


async def download_request_attachments(request_id: str, logger: logging.Logger = None, 
                                     download_path: str = "data/attachments") -> Dict[str, any]:
    """
    Download all available attachments for a specific request ID from Azure Blob Storage
    
    Args:
        request_id: The request ID to download attachments for
        logger: Logger instance for logging operations
        download_path: Local path to save downloaded files (default: "data/attachments")
    
    Returns:
        Dictionary containing download results and statistics
    """
    if not logger:
        logger = logging.getLogger(__name__)
    
    logger.info(f"Starting attachment download process for request ID: {request_id}")
    
    try:
        # Initialize database service
        db_service = DataService(main_logger=logger)
        
        # Load documents from database for the request
        logger.info(f"Fetching document records for request ID: {request_id}")
        documents_df = db_service.load_documents_by_request_id(request_id)
        
        if documents_df.empty:
            logger.info(f"No attachments found for request ID: {request_id}")
            return {
                "success": True,
                "message": "No attachments found for this request",
                "documents_found": 0,
                "downloads": {"success": [], "failed": [], "skipped": []}
            }
        
        logger.info(f"Found {len(documents_df)} document(s) for request ID: {request_id}")
        
        # Initialize blob download service
        try:
            blob_service = BlobDownloadService(logger=logger)
        except Exception as e:
            error_msg = f"Failed to initialize Azure Blob Storage service: {e}"
            logger.error(error_msg)
            return {
                "success": False,
                "message": error_msg,
                "documents_found": len(documents_df),
                "downloads": {"success": [], "failed": [], "skipped": []}
            }
        
        # Clean up old attachments for this request (optional)
        blob_service.cleanup_old_attachments(request_id, download_path)
        
        # Download attachments
        download_results = blob_service.download_request_attachments(
            request_id=request_id,
            documents_df=documents_df,
            download_path=download_path
        )
        
        # Prepare result summary
        total_downloads = len(download_results["success"])
        total_failed = len(download_results["failed"])
        total_skipped = len(download_results["skipped"])
        
        success_msg = (f"Attachment download completed for request {request_id}. "
                      f"Downloaded: {total_downloads}, Failed: {total_failed}, Skipped: {total_skipped}")
        
        logger.info(success_msg)
        
        return {
            "success": True,
            "message": success_msg,
            "documents_found": len(documents_df),
            "downloads": download_results,
            "download_path": str(Path(download_path) / f"request_{request_id}")
        }
        
    except Exception as e:
        error_msg = f"Error during attachment download for request {request_id}: {e}"
        logger.error(error_msg)
        return {
            "success": False,
            "message": error_msg,
            "documents_found": 0,
            "downloads": {"success": [], "failed": [], "skipped": []}
        }


def log_attachment_summary(download_result: Dict[str, any], logger: logging.Logger) -> None:
    """
    Log a detailed summary of the attachment download process
    
    Args:
        download_result: Result dictionary from download_request_attachments
        logger: Logger instance
    """
    if not download_result["success"]:
        logger.error(f"Attachment download failed: {download_result['message']}")
        return
    
    downloads = download_result.get("downloads", {})
    
    logger.info("=== ATTACHMENT DOWNLOAD SUMMARY ===")
    logger.info(f"Documents found in database: {download_result.get('documents_found', 0)}")
    logger.info(f"Successfully downloaded: {len(downloads.get('success', []))}")
    logger.info(f"Failed downloads: {len(downloads.get('failed', []))}")
    logger.info(f"Skipped files: {len(downloads.get('skipped', []))}")
    
    if downloads.get("success"):
        logger.info("Successfully downloaded files:")
        for file_path in downloads["success"]:
            logger.info(f"  - {Path(file_path).name}")
    
    if downloads.get("failed"):
        logger.warning("Failed to download files:")
        for filename in downloads["failed"]:
            logger.warning(f"  - {filename}")
    
    if downloads.get("skipped"):
        logger.info("Skipped files:")
        for filename in downloads["skipped"]:
            logger.info(f"  - {filename}")
    
    download_path = download_result.get("download_path")
    if download_path:
        logger.info(f"Files saved to: {download_path}")
    
    logger.info("=== END ATTACHMENT SUMMARY ===")


def validate_attachment_directory(request_id: str, download_path: str = "data/attachments") -> bool:
    """
    Validate that the attachment directory exists and contains files
    
    Args:
        request_id: The request ID to check
        download_path: Base download path
    
    Returns:
        True if directory exists and has files, False otherwise
    """
    request_dir = Path(download_path) / f"request_{request_id}"
    
    if not request_dir.exists():
        return False
    
    # Check if directory has any files
    files = list(request_dir.glob('*'))
    return len(files) > 0


def get_downloaded_attachments(request_id: str, download_path: str = "data/attachments") -> List[str]:
    """
    Get list of downloaded attachment files for a request
    
    Args:
        request_id: The request ID
        download_path: Base download path
    
    Returns:
        List of file paths for downloaded attachments
    """
    request_dir = Path(download_path) / f"request_{request_id}"
    
    if not request_dir.exists():
        return []
    
    return [str(file_path) for file_path in request_dir.glob('*') if file_path.is_file()]