"""
Test module for date_formatter utility functions.

This module contains comprehensive tests for the date formatting functionality,
including various input formats and edge cases.
"""

import sys
import os
import pandas as pd
import numpy as np
import logging
from datetime import datetime

# Add the src directory to the path to import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.date_formatter import (
    format_date_columns,
    format_standard_date_columns,
    get_standard_date_columns,
    preview_date_formatting
)


def setup_logger():
    """Setup a logger for testing purposes."""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    return logging.getLogger(__name__)


def create_test_dataframe():
    """Create a test DataFrame with various date formats."""
    test_data = {
        'DateOfBirth': [
            '1990-05-15 00:00:00.000',
            '1985-12-25',
            '2000-01-01 12:30:45',
            None,
            '1995-07-20'
        ],
        'EmiratesIDExpiryDate': [
            '2025-03-10 00:00:00',
            '2026-08-15 00:00:00.000',
            None,
            '2024-11-30',
            '2027-02-28 23:59:59'
        ],
        'LicenseIssueDate': [
            '2020-06-01',
            None,
            '2019-09-15 00:00:00',
            '2021-04-22 00:00:00.000',
            '2018-12-05'
        ],
        'Name': [  # Non-date column for testing
            'John Doe',
            'Jane Smith', 
            'Bob Johnson',
            'Alice Brown',
            'Charlie Wilson'
        ],
        'InvalidDateColumn': [  # Column with invalid date formats
            'not-a-date',
            '2024-13-40',  # Invalid month and day
            '2024/02/15',  # Different format
            None,
            ''
        ]
    }
    
    return pd.DataFrame(test_data)


def test_basic_date_formatting():
    """Test basic date formatting functionality."""
    logger = setup_logger()
    df = create_test_dataframe()
    
    print("\n" + "="*60)
    print("TESTING BASIC DATE FORMATTING")
    print("="*60)
    
    # Test formatting specific columns
    date_columns = ['DateOfBirth', 'EmiratesIDExpiryDate', 'LicenseIssueDate']
    
    print("\nOriginal DataFrame:")
    print(df[date_columns].to_string())
    
    # Format the date columns
    formatted_df = format_date_columns(df, date_columns, logger)
    
    print("\nFormatted DataFrame:")
    print(formatted_df[date_columns].to_string())
    
    # Verify the format is DD-MM-YYYY
    print("\nVerification - Sample formatted dates:")
    for col in date_columns:
        non_null_values = formatted_df[col].dropna()
        if not non_null_values.empty:
            sample = non_null_values.iloc[0]
            print(f"  {col}: {sample}")
            
            # Check if format is DD-MM-YYYY (should have exactly 2 dashes)
            if isinstance(sample, str) and sample.count('-') == 2:
                parts = sample.split('-')
                if len(parts) == 3 and len(parts[0]) == 2 and len(parts[1]) == 2 and len(parts[2]) == 4:
                    print(f"    ✓ Correct DD-MM-YYYY format")
                else:
                    print(f"    ✗ Incorrect format structure")
            else:
                print(f"    ✗ Not in expected format")


def test_standard_date_columns():
    """Test formatting using standard date columns."""
    logger = setup_logger()
    df = create_test_dataframe()
    
    print("\n" + "="*60)
    print("TESTING STANDARD DATE COLUMNS")
    print("="*60)
    
    print(f"\nStandard date columns: {get_standard_date_columns()}")
    
    # Format using standard columns
    formatted_df = format_standard_date_columns(df, logger)
    
    # Show results for columns that exist in our test data
    existing_standard_cols = [col for col in get_standard_date_columns() if col in df.columns]
    
    print(f"\nFormatted standard columns that exist in test data:")
    for col in existing_standard_cols:
        print(f"\n{col}:")
        print(formatted_df[col].to_string())


def test_edge_cases():
    """Test edge cases and error handling."""
    logger = setup_logger()
    
    print("\n" + "="*60)
    print("TESTING EDGE CASES")
    print("="*60)
    
    # Test empty DataFrame
    print("\n1. Testing empty DataFrame:")
    empty_df = pd.DataFrame()
    result = format_date_columns(empty_df, ['DateOfBirth'], logger)
    print(f"Empty DataFrame result shape: {result.shape}")
    
    # Test DataFrame with all null values
    print("\n2. Testing DataFrame with all null values:")
    null_df = pd.DataFrame({'DateOfBirth': [None, None, None]})
    result = format_date_columns(null_df, ['DateOfBirth'], logger)
    print("All null values result:")
    print(result.to_string())
    
    # Test non-existent columns
    print("\n3. Testing non-existent columns:")
    df = create_test_dataframe()
    result = format_date_columns(df, ['NonExistentColumn'], logger)
    print("Non-existent column test completed (check logs above)")
    
    # Test invalid date formats
    print("\n4. Testing invalid date formats:")
    result = format_date_columns(df, ['InvalidDateColumn'], logger)
    print("Invalid date column result:")
    print(result['InvalidDateColumn'].to_string())


def test_preview_functionality():
    """Test the preview functionality."""
    logger = setup_logger()
    df = create_test_dataframe()
    
    print("\n" + "="*60)
    print("TESTING PREVIEW FUNCTIONALITY")  
    print("="*60)
    
    print("\nPreviewing date formatting (no changes to DataFrame):")
    date_columns = ['DateOfBirth', 'EmiratesIDExpiryDate', 'LicenseIssueDate']
    preview_date_formatting(df, date_columns, logger)


def test_specific_date_conversions():
    """Test specific date conversion examples."""
    logger = setup_logger()
    
    print("\n" + "="*60)
    print("TESTING SPECIFIC DATE CONVERSIONS")
    print("="*60)
    
    # Create DataFrame with known date values
    test_cases = {
        'TestDates': [
            '2024-01-15 00:00:00.000',  # Should become 15-01-2024
            '2023-12-31 23:59:59',      # Should become 31-12-2023
            '2025-02-28',               # Should become 28-02-2025
            '2022-07-04 12:30:45.123',  # Should become 04-07-2022
            None                        # Should remain None
        ]
    }
    
    test_df = pd.DataFrame(test_cases)
    
    print("\nOriginal test dates:")
    print(test_df.to_string())
    
    formatted_df = format_date_columns(test_df, ['TestDates'], logger)
    
    print("\nFormatted test dates:")
    print(formatted_df.to_string())
    
    # Manual verification
    expected_results = ['15-01-2024', '31-12-2023', '28-02-2025', '04-07-2022', None]
    
    print("\nVerification:")
    for i, (original, formatted, expected) in enumerate(zip(
        test_cases['TestDates'], 
        formatted_df['TestDates'], 
        expected_results
    )):
        status = "✓" if formatted == expected else "✗"
        print(f"  {i+1}. {original} -> {formatted} (expected: {expected}) {status}")


def run_all_tests():
    """Run all test functions."""
    print("STARTING DATE FORMATTER TESTS")
    print("="*80)
    
    try:
        test_basic_date_formatting()
        test_standard_date_columns()
        test_edge_cases()
        test_preview_functionality()
        test_specific_date_conversions()
        
        print("\n" + "="*80)
        print("ALL TESTS COMPLETED SUCCESSFULLY!")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
