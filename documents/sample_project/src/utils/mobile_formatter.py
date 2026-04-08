"""
Mobile Number Formatting Utility Module

This module provides functions to format mobile number fields in DataFrames by adding "+" prefix.
Specifically designed to handle Mobile_CRM field from database and format it for CRM compatibility.
"""

import pandas as pd
import logging
from typing import List, Optional


def format_mobile_number(
    df: pd.DataFrame, 
    mobile_column: str = 'Mobile_CRM',
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """
    Format mobile number column in a DataFrame to add "+" prefix.
    
    Converts mobile numbers like '94714337912' to '+94714337912'
    
    Args:
        df: DataFrame to modify
        mobile_column: Name of the column containing mobile numbers (default: 'Mobile_CRM')
        logger: Optional logger instance for logging operations
        
    Returns:
        Modified DataFrame with formatted mobile number column
        
    Example:
        formatted_df = format_mobile_number(df, 'Mobile_CRM', logger)
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    try:
        # Create a copy of the DataFrame to avoid modifying the original
        result_df = df.copy()
        
        if result_df.empty:
            logger.warning("DataFrame is empty. Skipping mobile number formatting.")
            return result_df
        
        # Check if mobile column exists
        if mobile_column not in result_df.columns:
            logger.warning(f"Column '{mobile_column}' not found in DataFrame. Skipping mobile formatting.")
            return result_df
        
        logger.info(f"Starting mobile number formatting for column '{mobile_column}'")
        
        # Track formatting statistics
        formatted_count = 0
        skipped_count = 0
        already_formatted_count = 0
        
        def format_single_mobile(value):
            nonlocal formatted_count, skipped_count, already_formatted_count
            
            # Handle null values
            if pd.isna(value) or value is None:
                skipped_count += 1
                return None
            
            try:
                # Convert to string and strip whitespace
                mobile_str = str(value).strip()
                
                # Skip empty strings
                if not mobile_str:
                    skipped_count += 1
                    return None
                
                # Check if already has "+" prefix
                if mobile_str.startswith('+'):
                    already_formatted_count += 1
                    logger.debug(f"Mobile number '{mobile_str}' already has + prefix")
                    return mobile_str
                
                # Add "+" prefix to the mobile number
                formatted_mobile = f"+{mobile_str}"
                formatted_count += 1
                logger.debug(f"Formatted mobile number: '{mobile_str}' -> '{formatted_mobile}'")
                
                return formatted_mobile
                
            except Exception as e:
                logger.warning(f"Error formatting mobile number '{value}': {e}")
                skipped_count += 1
                return value  # Return original value if formatting fails
        
        # Apply formatting to the mobile column
        result_df[mobile_column] = result_df[mobile_column].apply(format_single_mobile)
        
        # Log summary
        total_processed = len(result_df)
        logger.info(f"Mobile number formatting completed for column '{mobile_column}':")
        logger.info(f"  - Total rows processed: {total_processed}")
        logger.info(f"  - Numbers formatted (+ added): {formatted_count}")
        logger.info(f"  - Already had + prefix: {already_formatted_count}")
        logger.info(f"  - Skipped (null/empty/error): {skipped_count}")
        
        # Show sample of formatted values
        if formatted_count > 0:
            sample_values = result_df[mobile_column].dropna().head(3).tolist()
            logger.info(f"  - Sample formatted values: {sample_values}")
        
        return result_df
        
    except Exception as e:
        logger.error(f"Error in mobile number formatting: {str(e)}")
        return df.copy()


def format_multiple_mobile_columns(
    df: pd.DataFrame, 
    mobile_columns: List[str],
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """
    Format multiple mobile number columns in a DataFrame to add "+" prefix.
    
    Args:
        df: DataFrame to modify
        mobile_columns: List of column names containing mobile numbers
        logger: Optional logger instance for logging operations
        
    Returns:
        Modified DataFrame with formatted mobile number columns
        
    Example:
        mobile_cols = ['Mobile_CRM', 'AlternateMobile', 'EmergencyContact']
        formatted_df = format_multiple_mobile_columns(df, mobile_cols, logger)
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    try:
        result_df = df.copy()
        
        logger.info(f"Starting mobile number formatting for {len(mobile_columns)} columns")
        
        for i, col in enumerate(mobile_columns, 1):
            logger.info(f"Processing column {i}/{len(mobile_columns)}: {col}")
            result_df = format_mobile_number(result_df, col, logger)
        
        logger.info("All mobile number columns formatted successfully")
        return result_df
        
    except Exception as e:
        logger.error(f"Error formatting multiple mobile columns: {str(e)}")
        return df.copy()


def get_standard_mobile_columns() -> List[str]:
    """
    Get the standard list of mobile number columns that typically need formatting.
    
    Returns:
        List of standard mobile column names
    """
    return ['Mobile_CRM']


def format_standard_mobile_columns(
    df: pd.DataFrame, 
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """
    Convenience function to format the standard mobile number columns.
    
    Args:
        df: DataFrame to modify
        logger: Optional logger instance
        
    Returns:
        DataFrame with formatted standard mobile number columns
        
    Example:
        formatted_df = format_standard_mobile_columns(customer_df, logger)
    """
    standard_columns = get_standard_mobile_columns()
    return format_multiple_mobile_columns(df, standard_columns, logger)


def preview_mobile_formatting(
    df: pd.DataFrame, 
    mobile_columns: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None
) -> None:
    """
    Preview how mobile number columns will look after formatting without modifying the DataFrame.
    Useful for debugging and validation.
    
    Args:
        df: DataFrame to preview
        mobile_columns: List of mobile columns to preview (defaults to standard columns)
        logger: Optional logger instance
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    if mobile_columns is None:
        mobile_columns = get_standard_mobile_columns()
    
    logger.info("Mobile number formatting preview:")
    
    for col in mobile_columns:
        if col not in df.columns:
            logger.info(f"  {col}: Column not found")
            continue
        
        if df[col].isna().all():
            logger.info(f"  {col}: All null values")
            continue
        
        # Get first non-null value as example
        sample_value = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
        
        if sample_value is not None:
            try:
                sample_str = str(sample_value).strip()
                if sample_str.startswith('+'):
                    formatted_sample = sample_str
                    status = "(already formatted)"
                else:
                    formatted_sample = f"+{sample_str}"
                    status = "(will be formatted)"
                
                logger.info(f"  {col}: '{sample_value}' -> '{formatted_sample}' {status}")
            except Exception as e:
                logger.info(f"  {col}: Error previewing '{sample_value}': {str(e)}")
        else:
            logger.info(f"  {col}: No non-null values found")


def validate_mobile_format(mobile_number: str) -> bool:
    """
    Validate if a mobile number has the correct format (starts with +).
    
    Args:
        mobile_number: The mobile number string to validate
        
    Returns:
        True if mobile number starts with +, False otherwise
    """
    if not mobile_number or pd.isna(mobile_number):
        return False
    
    return str(mobile_number).strip().startswith('+')