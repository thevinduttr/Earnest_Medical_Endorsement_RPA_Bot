"""
Test to verify ALL document types including "other_document" are attached to error emails
"""
import os
from pathlib import Path
import tempfile
import shutil

def test_all_documents_retrieved():
    """
    Verify that get_downloaded_attachments retrieves ALL files including other_document
    """
    from src.utils.attachment_manager import get_downloaded_attachments
    
    # Create test directory structure
    test_request_id = "test_123456"
    test_attachments_dir = Path("data/attachments_test")
    test_request_dir = test_attachments_dir / f"request_{test_request_id}"
    test_request_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Create test files of various document types
        test_files = [
            "EMIRATES_ID.pdf",
            "DRIVING_LICENSE.pdf",
            "MULKIYA.pdf",
            "E_MULKIYA_HYSA.pdf",
            "VCC.pdf",
            "PCD_HYSA.pdf",
            "KAVAK_QUOTATION.pdf",
            "ALBA_QUOTATION.pdf",
            "other_document.pdf",  # ← THIS IS THE KEY ONE
            "some_random_file.jpg",
            "another_document.docx",
            "extra_file.png"
        ]
        
        # Create actual test files
        for filename in test_files:
            test_file = test_request_dir / filename
            test_file.write_text(f"Test content for {filename}")
        
        print(f"✓ Created {len(test_files)} test files")
        print(f"  Files: {', '.join(test_files)}")
        print()
        
        # Test: Retrieve attachments using the actual function
        retrieved_files = get_downloaded_attachments(
            request_id=test_request_id,
            download_path=str(test_attachments_dir)
        )
        
        print(f"✓ Retrieved {len(retrieved_files)} files using get_downloaded_attachments()")
        print(f"  Expected: {len(test_files)}")
        print()
        
        # Extract just filenames for comparison
        retrieved_filenames = [Path(f).name for f in retrieved_files]
        retrieved_filenames.sort()
        test_files.sort()
        
        print("Retrieved files:")
        for filename in retrieved_filenames:
            print(f"  ✓ {filename}")
        print()
        
        # Verify ALL files were retrieved
        if retrieved_filenames == test_files:
            print("✅ SUCCESS: ALL documents retrieved including 'other_document.pdf'")
            print("✅ The glob('*') pattern correctly gets EVERY file")
            return True
        else:
            print("❌ FAILURE: Some files were missing")
            missing = set(test_files) - set(retrieved_filenames)
            extra = set(retrieved_filenames) - set(test_files)
            if missing:
                print(f"   Missing: {missing}")
            if extra:
                print(f"   Extra: {extra}")
            return False
            
    finally:
        # Cleanup test directory
        if test_attachments_dir.exists():
            shutil.rmtree(test_attachments_dir)
            print(f"\n✓ Cleaned up test directory")

if __name__ == "__main__":
    print("=" * 70)
    print("TESTING: Do error emails include ALL document types?")
    print("Including: other_document.pdf and any other uploaded files")
    print("=" * 70)
    print()
    
    success = test_all_documents_retrieved()
    
    print()
    print("=" * 70)
    if success:
        print("✅ CONFIRMED: All documents including 'other_document' ARE attached")
        print("✅ No filtering - every file in request folder is attached")
    else:
        print("❌ Issue detected - some files not retrieved")
    print("=" * 70)
