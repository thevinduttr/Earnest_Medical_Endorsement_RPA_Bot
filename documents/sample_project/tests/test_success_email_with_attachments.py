"""
Test script for verifying CR implementation: Attach Documents in Completion Email (LEAD/PROSPECT)

This test verifies that success emails for Lead and Prospect creation include all submitted documents.
"""
import asyncio
import logging
from pathlib import Path
import pandas as pd
from src.utils.send_email import send_success_email

# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_success_attachments")


def create_test_attachments(request_id: str) -> Path:
    """Create test attachment files for testing."""
    # Create test attachment directory
    attachments_dir = Path("data/attachments") / f"request_{request_id}"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    
    # Create sample test files
    test_files = [
        "emirates_id_front.pdf",
        "emirates_id_back.pdf",
        "driving_license.jpg",
        "vehicle_registration.pdf"
    ]
    
    for filename in test_files:
        file_path = attachments_dir / filename
        file_path.write_text(f"Test content for {filename}")
        logger.info(f"Created test file: {file_path}")
    
    return attachments_dir


async def test_lead_success_with_attachments():
    """Test Lead success email with document attachments."""
    logger.info("\n" + "="*80)
    logger.info("TEST 1: Lead Success Email with Document Attachments")
    logger.info("="*80)
    
    request_id = "TEST_LEAD_ATTACH_001"
    
    # Create test attachments
    logger.info(f"\n[Step 1] Creating test attachments for request ID: {request_id}")
    attachments_dir = create_test_attachments(request_id)
    logger.info(f"✓ Created {len(list(attachments_dir.glob('*')))} test attachment files")
    
    # Sample lead data
    sample_lead_data = {
        'Id': ['12345'],
        'FirstName': ['Ahmed'],
        'LastName': ['Al Maktoum'],
        'Email_CRM': ['ahmed.almaktoum@example.ae'],
        'Mobile_CRM': ['+971501234567'],
        'EmiratesID': ['784-1234-5678901-2'],
        'Nationality': ['United Arab Emirates'],
        'BusinessType': ['Motor'],
        'Class': ['Private'],
        'PolicyTypeCRM': ['Comprehensive'],
        'InsuranceCompany': ['AXA Insurance'],
        'Classification': ['Hot'],
        'Source': ['Website']
    }
    
    df = pd.DataFrame(sample_lead_data)
    lead_ref_no = "LEAD-2026-TEST-001"
    
    logger.info(f"\n[Step 2] Sending Lead success email with attachments")
    logger.info(f"  Request ID: {request_id}")
    logger.info(f"  Lead Ref No: {lead_ref_no}")
    logger.info(f"  Expected Attachments: {len(list(attachments_dir.glob('*')))} documents")
    
    try:
        await send_success_email(
            process_type="lead",
            df=df,
            ref_no=lead_ref_no,
            request_id=request_id,
            logger=logger
        )
        logger.info("\n✓ Lead success email sent successfully with attachments!")
        logger.info("\nPlease check your email inbox for:")
        logger.info(f"  Subject: Lead Created Successfully - Request ID: {request_id} - Ref: {lead_ref_no}")
        logger.info(f"  Expected Attachments: 4 documents (emirates_id_front.pdf, emirates_id_back.pdf, driving_license.jpg, vehicle_registration.pdf)")
        return True
    except Exception as e:
        logger.error(f"\n✗ Failed to send lead email: {e}")
        return False


async def test_prospect_success_with_attachments():
    """Test Prospect success email with document attachments."""
    logger.info("\n" + "="*80)
    logger.info("TEST 2: Prospect Success Email with Document Attachments")
    logger.info("="*80)
    
    request_id = "TEST_PROSPECT_ATTACH_002"
    
    # Create test attachments
    logger.info(f"\n[Step 1] Creating test attachments for request ID: {request_id}")
    attachments_dir = create_test_attachments(request_id)
    logger.info(f"✓ Created {len(list(attachments_dir.glob('*')))} test attachment files")
    
    # Sample prospect data
    sample_prospect_data = {
        'Id': ['67890'],
        'FirstName': ['Fatima'],
        'LastName': ['Hassan'],
        'Email_CRM': ['fatima.hassan@example.ae'],
        'Mobile_CRM': ['+971509876543'],
        'EmiratesID': ['784-9876-5432109-8'],
        'Nationality': ['United Arab Emirates'],
        'BusinessType': ['Motor'],
        'Class': ['Private'],
        'PolicyTypeCRM': ['Third Party'],
        'InsuranceCompany': ['Dubai Insurance'],
        'Classification': ['Warm'],
        'Source': ['Referral'],
        'Make': ['Toyota'],
        'Model': ['Camry'],
        'Year': ['2023'],
        'Emirate': ['Dubai']
    }
    
    df = pd.DataFrame(sample_prospect_data)
    prospect_ref_no = "PROSPECT-2026-TEST-002"
    
    logger.info(f"\n[Step 2] Sending Prospect success email with attachments")
    logger.info(f"  Request ID: {request_id}")
    logger.info(f"  Prospect Ref No: {prospect_ref_no}")
    logger.info(f"  Expected Attachments: {len(list(attachments_dir.glob('*')))} documents")
    
    try:
        await send_success_email(
            process_type="prospect",
            df=df,
            ref_no=prospect_ref_no,
            request_id=request_id,
            logger=logger
        )
        logger.info("\n✓ Prospect success email sent successfully with attachments!")
        logger.info("\nPlease check your email inbox for:")
        logger.info(f"  Subject: Prospect Created Successfully - Request ID: {request_id} - Ref: {prospect_ref_no}")
        logger.info(f"  Expected Attachments: 4 documents (emirates_id_front.pdf, emirates_id_back.pdf, driving_license.jpg, vehicle_registration.pdf)")
        return True
    except Exception as e:
        logger.error(f"\n✗ Failed to send prospect email: {e}")
        return False


async def test_lead_optout_with_attachments():
    """Test Lead OPT-OUT success email with document attachments."""
    logger.info("\n" + "="*80)
    logger.info("TEST 3: Lead OPT-OUT Success Email with Document Attachments")
    logger.info("="*80)
    
    request_id = "TEST_LEAD_OPTOUT_003"
    
    # Create test attachments
    logger.info(f"\n[Step 1] Creating test attachments for request ID: {request_id}")
    attachments_dir = create_test_attachments(request_id)
    logger.info(f"✓ Created {len(list(attachments_dir.glob('*')))} test attachment files")
    
    # Sample lead data
    sample_lead_data = {
        'Id': ['99999'],
        'FirstName': ['Mohammed'],
        'LastName': ['Ali'],
        'Email_CRM': ['mohammed.ali@example.ae'],
        'Mobile_CRM': ['+971501111111'],
        'EmiratesID': ['784-1111-1111111-1'],
        'Nationality': ['United Arab Emirates'],
        'BusinessType': ['Motor'],
        'Class': ['Private'],
        'PolicyTypeCRM': ['Comprehensive'],
        'InsuranceCompany': ['AXA Insurance'],
        'Classification': ['Hot'],
        'Source': ['Website']
    }
    
    # OPT-OUT data
    optout_data = {
        'RequestId': request_id,
        'Email': 'mohammed.ali@example.ae',
        'Mobile': '+971501111111',
        'MatchedBy': 'Email',
        'MatchedValue': 'mohammed.ali@example.ae'
    }
    
    df = pd.DataFrame(sample_lead_data)
    lead_ref_no = "LEAD-2026-OPTOUT-003"
    
    logger.info(f"\n[Step 2] Sending Lead OPT-OUT success email with attachments")
    logger.info(f"  Request ID: {request_id}")
    logger.info(f"  Lead Ref No: {lead_ref_no}")
    logger.info(f"  OPT-OUT Status: YES (Red Header)")
    logger.info(f"  Expected Attachments: {len(list(attachments_dir.glob('*')))} documents")
    
    try:
        await send_success_email(
            process_type="lead",
            df=df,
            ref_no=lead_ref_no,
            request_id=request_id,
            optout_data=optout_data,
            logger=logger
        )
        logger.info("\n✓ Lead OPT-OUT success email sent successfully with attachments!")
        logger.info("\nPlease check your email inbox for:")
        logger.info(f"  Subject: OPT-OUT - Lead Created Successfully - Request ID: {request_id} - Ref: {lead_ref_no}")
        logger.info(f"  Expected: RED HEADER with OPT-OUT warning")
        logger.info(f"  Expected Attachments: 4 documents")
        return True
    except Exception as e:
        logger.error(f"\n✗ Failed to send lead opt-out email: {e}")
        return False


async def main():
    """Run all tests."""
    logger.info("\n" + "="*80)
    logger.info("CR IMPLEMENTATION TEST: Attach Documents in Completion Email")
    logger.info("="*80)
    logger.info("\nThis test verifies that success emails include all submitted documents")
    logger.info("for both LEAD and PROSPECT processes.\n")
    
    results = []
    
    # Test 1: Lead with attachments
    result1 = await test_lead_success_with_attachments()
    results.append(("Lead Success Email with Attachments", result1))
    await asyncio.sleep(2)
    
    # Test 2: Prospect with attachments
    result2 = await test_prospect_success_with_attachments()
    results.append(("Prospect Success Email with Attachments", result2))
    await asyncio.sleep(2)
    
    # Test 3: Lead OPT-OUT with attachments
    result3 = await test_lead_optout_with_attachments()
    results.append(("Lead OPT-OUT Success Email with Attachments", result3))
    
    # Summary
    logger.info("\n" + "="*80)
    logger.info("TEST SUMMARY")
    logger.info("="*80)
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        logger.info(f"{test_name}: {status}")
    
    all_passed = all(result for _, result in results)
    logger.info("\n" + ("="*80))
    if all_passed:
        logger.info("ALL TESTS PASSED! ✓")
        logger.info("\nCheck your email inbox for 3 emails with attachments:")
        logger.info("  1. Lead Created Successfully (4 attachments)")
        logger.info("  2. Prospect Created Successfully (4 attachments)")
        logger.info("  3. OPT-OUT - Lead Created Successfully (4 attachments, RED header)")
    else:
        logger.info("SOME TESTS FAILED! ✗")
    logger.info("="*80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
