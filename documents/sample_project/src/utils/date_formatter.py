"""
Date Formatting Utility Module

This module provides functions to format date columns in DataFrames by removing time components.
Specifically designed to handle database datetime values and convert them to DD-MM-YYYY format.
"""

import pandas as pd
import logging
from typing import List, Optional


def format_date_columns(
    df: pd.DataFrame, 
    date_columns: List[str], 
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """
    Format date columns in a DataFrame to remove time components.
    
    Converts datetime values like '2027-02-26 00:00:00.000' to '26-02-2027'
    
    Args:
        df: DataFrame to modify
        date_columns: List of column names that contain date values
        logger: Optional logger instance for logging operations
        
    Returns:
        Modified DataFrame with formatted date columns
        
    Example:
        date_cols = ['DateOfBirth', 'EmiratesIDExpiryDate', 'LicenseIssueDate']
        formatted_df = format_date_columns(df, date_cols, logger)
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    try:
        # Create a copy of the DataFrame to avoid modifying the original
        result_df = df.copy()
        
        if result_df.empty:
            logger.warning("DataFrame is empty. Skipping date formatting.")
            return result_df
        
        # Track which columns were successfully formatted
        formatted_columns = []
        skipped_columns = []
        
        logger.info(f"Starting date formatting for {len(date_columns)} columns")
        
        for col in date_columns:
            if col not in result_df.columns:
                skipped_columns.append(col)
                logger.warning(f"Column '{col}' not found in DataFrame. Skipping.")
                continue
            
            try:
                # Check if column has any non-null values
                if result_df[col].isna().all():
                    skipped_columns.append(col)
                    logger.info(f"Column '{col}' contains only null values. Skipping.")
                    continue
                
                # Process each value individually to avoid pandas series inference issues
                def format_single_date(value):
                    # Handle null values
                    if pd.isna(value) or value is None:
                        return None
                    
                    try:
                        # Convert individual value to datetime
                        dt = pd.to_datetime(value, errors='coerce')
                        
                        # Check if conversion was successful
                        if pd.isna(dt):
                            logger.warning(f"Could not parse date value '{value}' in column '{col}'")
                            return None
                        
                        # Format as date string (DD-MM-YYYY)
                        return dt.strftime('%d-%m-%Y')
                        
                    except Exception as e:
                        logger.warning(f"Error formatting date value '{value}' in column '{col}': {e}")
                        return None
                
                # Apply formatting to each value individually
                result_df[col] = result_df[col].apply(format_single_date)
                
                formatted_columns.append(col)
                logger.debug(f"Successfully formatted column '{col}'")
                
            except Exception as col_error:
                logger.error(f"Error formatting column '{col}': {str(col_error)}")
                skipped_columns.append(col)
        
        # Log summary
        logger.info(f"Date formatting completed:")
        logger.info(f"  - Successfully formatted: {len(formatted_columns)} columns")
        logger.info(f"  - Skipped: {len(skipped_columns)} columns")
        
        if formatted_columns:
            logger.info(f"  - Formatted columns: {', '.join(formatted_columns)}")
        
        if skipped_columns:
            logger.warning(f"  - Skipped columns: {', '.join(skipped_columns)}")
        
        return result_df
        
    except Exception as e:
        logger.error(f"Error in date formatting: {str(e)}")
        return df.copy()


def get_standard_date_columns() -> List[str]:
    """
    Get the standard list of date columns that typically need formatting.
    
    Returns:
        List of standard date column names
    """
    return [
        'DateOfBirth',
        'EmiratesIDExpiryDate', 
        'LicenseIssueDate',
        'LicenseExpiryDate',
        'DateOfFirstRegistration',
        'EmiratesIDIssueDate'
    ]


def format_standard_date_columns(
    df: pd.DataFrame, 
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """
    Convenience function to format the standard date columns.
    
    Args:
        df: DataFrame to modify
        logger: Optional logger instance
        
    Returns:
        DataFrame with formatted standard date columns
        
    Example:
        formatted_df = format_standard_date_columns(customer_df, logger)
    """
    standard_columns = get_standard_date_columns()
    return format_date_columns(df, standard_columns, logger)


def preview_date_formatting(
    df: pd.DataFrame, 
    date_columns: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None
) -> None:
    """
    Preview how date columns will look after formatting without modifying the DataFrame.
    Useful for debugging and validation.
    
    Args:
        df: DataFrame to preview
        date_columns: List of date columns to preview (defaults to standard columns)
        logger: Optional logger instance
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    if date_columns is None:
        date_columns = get_standard_date_columns()
    
    logger.info("Date formatting preview:")
    
    for col in date_columns:
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
                # Show what the formatted value would look like
                formatted_sample = pd.to_datetime(sample_value, errors='coerce').strftime('%d-%m-%Y')
                logger.info(f"  {col}: '{sample_value}' -> '{formatted_sample}'")
            except Exception as e:
                logger.info(f"  {col}: Error formatting '{sample_value}': {str(e)}")
        else:
            logger.info(f"  {col}: No non-null values found")