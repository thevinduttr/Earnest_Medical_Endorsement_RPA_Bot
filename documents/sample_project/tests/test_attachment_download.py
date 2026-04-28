"""
Test script for attachment download functionality
Run this to test the attachment download process independently
"""

import asyncio
import logging
from pathlib import Path
import sys
import os

# Add the project root to the Python path
sys.path.append(str(Path(__file__).parent))

from src.utils.attachment_manager import download_request_attachments, log_attachment_summary

async def test_attachment_download():
    """Test the attachment download functionality"""
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger('test_attachment_download')
    
    # Test request ID (replace with a real request ID from your database)
    test_request_id = "212419000"  # Change this to a real request ID
    
    logger.info(f"Testing attachment download for request ID: {test_request_id}")
    
    try:
        # Test the download process
        result = await download_request_attachments(
            request_id=test_request_id,
            logger=logger,
            download_path="data/test_attachment_download"
        )
        
        # Log the results
        log_attachment_summary(result, logger)
        
        if result["success"]:
            logger.info("✅ Attachment download test completed successfully!")
            
            if result["documents_found"] > 0:
                logger.info(f"Found {result['documents_found']} documents in database")
                downloads = result["downloads"]
                logger.info(f"Downloaded: {len(downloads['success'])} files")
                logger.info(f"Failed: {len(downloads['failed'])} files")
                logger.info(f"Skipped: {len(downloads['skipped'])} files")
            else:
                logger.info("No documents found for this request ID")
        else:
            logger.error(f"❌ Attachment download test failed: {result['message']}")
    
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")

if __name__ == "__main__":
    print("=" * 60)
    print("ATTACHMENT DOWNLOAD TEST")
    print("=" * 60)
    print()
    print("This script tests the attachment download functionality.")
    print("Make sure to:")
    print("1. Set up your Azure Storage connection string in config/env/blob.env")
    print("2. Replace the test_request_id with a real request ID from your database")
    print("3. Ensure your database connection is working")
    print()
    
    # Prompt for confirmation
    response = input("Do you want to continue with the test? (y/N): ").strip().lower()
    if response != 'y':
        print("Test cancelled.")
        sys.exit(0)
    
    # Run the test
    asyncio.run(test_attachment_download())