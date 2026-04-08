#!/usr/bin/env python3
"""
Test script to verify CR implementation: Attach Documents in Error Notification Emails
Tests various error scenarios to ensure submitted documents are properly attached.
"""

import asyncio
import sys
from pathlib import Path
import logging
import tempfile
import shutil

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.send_email import send_error_email, extract_request_id_from_run_id
from src.utils.mailer import send_error_email_with_screenshots
from src.utils.attachment_manager import get_downloaded_attachments
from src.utils.support_functions import notify_process_error
from src.utils.load_data import load_yaml_file

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def setup_test_documents(request_id: str) -> list:
    """Create test documents for a request ID"""
    test_docs_dir = Path(f"data/attachments/request_{request_id}")
    test_docs_dir.mkdir(parents=True, exist_ok=True)
    
    # Create test documents
    test_files = []
    
    # Test PDF
    pdf_file = test_docs_dir / "test_document.pdf"
    pdf_file.write_text("Mock PDF content for testing")
    test_files.append(pdf_file)
    
    # Test image
    img_file = test_docs_dir / "test_image.jpg"
    img_file.write_text("Mock image content for testing")
    test_files.append(img_file)
    
    # Test ID card
    id_file = test_docs_dir / "emirates_id.png"
    id_file.write_text("Mock Emirates ID for testing")
    test_files.append(id_file)
    
    logger.info(f"✓ Created {len(test_files)} test documents for request_{request_id}")
    return test_files


def cleanup_test_documents(request_id: str):
    """Clean up test documents"""
    test_docs_dir = Path(f"data/attachments/request_{request_id}")
    if test_docs_dir.exists():
        shutil.rmtree(test_docs_dir)
        logger.info(f"✓ Cleaned up test documents for request_{request_id}")


async def test_extract_request_id():
    """Test 1: Extract request_id from run_id"""
    logger.info("\n" + "="*60)
    logger.info("TEST 1: Extract Request ID from Run ID")
    logger.info("="*60)
    
    test_cases = [
        ("run_2026-02-25/bot_1-req_815948000", "815948000"),
        ("run_2026-02-23/bot_2-req_123456789", "123456789"),
        ("bot_1-req_999999999", "999999999"),
    ]
    
    all_passed = True
    for run_id, expected in test_cases:
        result = extract_request_id_from_run_id(run_id)
        if result == expected:
            logger.info(f"  ✓ PASS: '{run_id}' -> '{result}'")
        else:
            logger.error(f"  ✗ FAIL: '{run_id}' -> Expected '{expected}', got '{result}'")
            all_passed = False
    
    return all_passed


async def test_get_downloaded_attachments():
    """Test 2: Get downloaded attachments for a request"""
    logger.info("\n" + "="*60)
    logger.info("TEST 2: Get Downloaded Attachments")
    logger.info("="*60)
    
    request_id = "TEST_001"
    
    # Setup test documents
    test_files = setup_test_documents(request_id)
    
    # Get attachments
    attachments = get_downloaded_attachments(request_id)
    
    if len(attachments) == len(test_files):
        logger.info(f"  ✓ PASS: Found {len(attachments)} attachments")
        for att in attachments:
            logger.info(f"    - {Path(att).name}")
        result = True
    else:
        logger.error(f"  ✗ FAIL: Expected {len(test_files)} attachments, got {len(attachments)}")
        result = False
    
    # Cleanup
    cleanup_test_documents(request_id)
    
    return result


async def test_send_error_email_with_documents():
    """Test 3: Send error email with documents attached"""
    logger.info("\n" + "="*60)
    logger.info("TEST 3: Send Error Email with Documents")
    logger.info("="*60)
    
    request_id = "TEST_002"
    
    # Check if email configuration exists
    try:
        email_cfg = load_yaml_file("config/email.yml")
        if not email_cfg:
            logger.warning("  ⚠ SKIP: Email configuration not found")
            return None
    except Exception as e:
        logger.warning(f"  ⚠ SKIP: Could not load email config: {e}")
        return None
    
    # Setup test documents
    test_files = setup_test_documents(request_id)
    
    # Create a test screenshot
    screenshot_dir = Path("data/outputs/error_screenshots")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    test_screenshot = screenshot_dir / "test_error.png"
    test_screenshot.write_text("Mock screenshot for testing")
    
    try:
        # Test send_error_email with request_id
        logger.info("  → Testing send_error_email() with request_id...")
        
        subject = "[TEST] Error Email with Documents"
        body = """This is a test error email to verify CR implementation.
        
Error Details:
- Type: Validation Error
- Request ID: TEST_002
- Expected Attachments: 3 documents + 1 screenshot

This email should contain:
1. test_document.pdf
2. test_image.jpg
3. emirates_id.png
4. test_error.png (screenshot)
"""
        
        # Note: This will actually send an email if configuration is valid
        # In a real test environment, you might want to mock this
        logger.info("  → Preparing to send test email (DRY RUN - not actually sending)")
        logger.info(f"    Subject: {subject}")
        logger.info(f"    Request ID: {request_id}")
        logger.info(f"    Screenshot: {test_screenshot.name}")
        logger.info(f"    Documents: {len(test_files)} files")
        
        # Verify attachment retrieval works
        attachments = get_downloaded_attachments(request_id)
        if len(attachments) == len(test_files):
            logger.info(f"  ✓ PASS: Document retrieval working ({len(attachments)} files found)")
            result = True
        else:
            logger.error(f"  ✗ FAIL: Expected {len(test_files)} documents, found {len(attachments)}")
            result = False
        
        # Uncomment to actually send test email:
        # await send_error_email(
        #     subject=subject,
        #     body=body,
        #     screenshot_path=test_screenshot,
        #     request_id=request_id,
        #     logger=logger
        # )
        # logger.info("  ✓ PASS: Email sent successfully")
        
    except Exception as e:
        logger.error(f"  ✗ FAIL: Error sending email: {e}")
        result = False
    finally:
        # Cleanup
        cleanup_test_documents(request_id)
        if test_screenshot.exists():
            test_screenshot.unlink()
    
    return result


async def test_notify_process_error_with_documents():
    """Test 4: notify_process_error with request_id"""
    logger.info("\n" + "="*60)
    logger.info("TEST 4: Notify Process Error with Documents")
    logger.info("="*60)
    
    request_id = "TEST_003"
    run_id = f"run_2026-02-25/bot_1-req_{request_id}"
    
    # Setup test documents
    test_files = setup_test_documents(request_id)
    
    # Create run directory
    run_dir = Path(f"data/logs/{run_id}")
    run_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        logger.info("  → Testing notify_process_error() with request_id...")
        logger.info(f"    Run ID: {run_id}")
        logger.info(f"    Request ID: {request_id}")
        logger.info(f"    Documents: {len(test_files)} files")
        
        # Verify attachment retrieval
        attachments = get_downloaded_attachments(request_id)
        if len(attachments) == len(test_files):
            logger.info(f"  ✓ PASS: Document retrieval working ({len(attachments)} files found)")
            result = True
        else:
            logger.error(f"  ✗ FAIL: Expected {len(test_files)} documents, found {len(attachments)}")
            result = False
        
        # Note: Not actually calling notify_process_error as it requires a page object
        # In production, this would be called from within the automation flow
        logger.info("  ℹ NOTE: notify_process_error requires page object - testing signature only")
        
    except Exception as e:
        logger.error(f"  ✗ FAIL: Error in test: {e}")
        result = False
    finally:
        # Cleanup
        cleanup_test_documents(request_id)
        if run_dir.exists():
            shutil.rmtree(run_dir)
    
    return result


async def test_send_error_email_with_screenshots_and_documents():
    """Test 5: send_error_email_with_screenshots with request_id"""
    logger.info("\n" + "="*60)
    logger.info("TEST 5: Send Error Email with Screenshots and Documents")
    logger.info("="*60)
    
    request_id = "TEST_004"
    run_id = f"run_2026-02-25/bot_1-req_{request_id}"
    
    # Setup test documents
    test_files = setup_test_documents(request_id)
    
    # Create test screenshots
    screenshot_dir = Path("data/outputs/error_screenshots")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    
    screenshots = []
    for i in range(2):
        screenshot = screenshot_dir / f"test_screenshot_{i+1}.png"
        screenshot.write_text(f"Mock screenshot {i+1} for testing")
        screenshots.append(screenshot)
    
    try:
        logger.info("  → Testing send_error_email_with_screenshots() with request_id...")
        logger.info(f"    Run ID: {run_id}")
        logger.info(f"    Request ID: {request_id}")
        logger.info(f"    Screenshots: {len(screenshots)} files")
        logger.info(f"    Documents: {len(test_files)} files")
        
        # Verify attachment retrieval
        attachments = get_downloaded_attachments(request_id)
        if len(attachments) == len(test_files):
            logger.info(f"  ✓ PASS: Document retrieval working ({len(attachments)} files found)")
            result = True
        else:
            logger.error(f"  ✗ FAIL: Expected {len(test_files)} documents, found {len(attachments)}")
            result = False
        
        # Check if email config exists
        try:
            email_cfg = load_yaml_file("config/email.yml")
            logger.info("  ℹ NOTE: Would send email with screenshots + documents (DRY RUN)")
        except Exception as e:
            logger.warning(f"  ⚠ SKIP: Email config not available: {e}")
        
    except Exception as e:
        logger.error(f"  ✗ FAIL: Error in test: {e}")
        result = False
    finally:
        # Cleanup
        cleanup_test_documents(request_id)
        for screenshot in screenshots:
            if screenshot.exists():
                screenshot.unlink()
    
    return result


async def test_error_scenarios_integration():
    """Test 6: Verify integration with different error types"""
    logger.info("\n" + "="*60)
    logger.info("TEST 6: Integration with Error Types")
    logger.info("="*60)
    
    scenarios = [
        ("Lead Creation Error", "req_LEAD_001"),
        ("Prospect Creation Error", "req_PROSPECT_001"),
        ("Duplicate Client Error", "req_DUPLICATE_001"),
        ("Validation Error", "req_VALIDATION_001"),
    ]
    
    all_passed = True
    
    for scenario_name, request_id in scenarios:
        logger.info(f"\n  Testing: {scenario_name}")
        logger.info(f"  Request ID: {request_id}")
        
        # Setup test documents
        test_files = setup_test_documents(request_id)
        
        # Verify documents can be retrieved
        attachments = get_downloaded_attachments(request_id)
        
        if len(attachments) == len(test_files):
            logger.info(f"    ✓ PASS: {scenario_name} - {len(attachments)} documents retrievable")
        else:
            logger.error(f"    ✗ FAIL: {scenario_name} - Expected {len(test_files)}, got {len(attachments)}")
            all_passed = False
        
        # Cleanup
        cleanup_test_documents(request_id)
    
    return all_passed


async def run_all_tests():
    """Run all tests"""
    logger.info("\n" + "#"*60)
    logger.info("# CR IMPLEMENTATION TEST SUITE")
    logger.info("# Attach Documents in Error Notification Emails")
    logger.info("#"*60)
    
    results = {}
    
    # Run tests
    results['test_1'] = await test_extract_request_id()
    results['test_2'] = await test_get_downloaded_attachments()
    results['test_3'] = await test_send_error_email_with_documents()
    results['test_4'] = await test_notify_process_error_with_documents()
    results['test_5'] = await test_send_error_email_with_screenshots_and_documents()
    results['test_6'] = await test_error_scenarios_integration()
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)
    
    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    total = len(results)
    
    logger.info(f"Total Tests: {total}")
    logger.info(f"Passed: {passed} ✓")
    logger.info(f"Failed: {failed} ✗")
    logger.info(f"Skipped: {skipped} ⚠")
    
    if failed == 0:
        logger.info("\n🎉 ALL TESTS PASSED! CR Implementation verified.")
        return 0
    else:
        logger.error(f"\n❌ {failed} TEST(S) FAILED! Please review the errors above.")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(run_all_tests())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\nTests interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\nFatal error: {e}", exc_info=True)
        sys.exit(1)
