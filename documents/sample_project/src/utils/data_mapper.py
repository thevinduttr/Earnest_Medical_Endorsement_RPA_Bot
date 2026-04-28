"""
Data Mapping Utility Module

This module provides generic functions to map values in DataFrames using mapping tables.
It supports mapping any column values based on database lookup tables.
"""

import pandas as pd
import logging
from typing import Dict, List, Optional, Any

try:
    from ..services.db_service.data_service import DataService
except ImportError:
    # Handle case when running as standalone module
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))
    from services.db_service.data_service import DataService


class DataMapper:
    """
    Generic data mapping utility for transforming DataFrame values using database mapping tables.
    """
    
    def __init__(self, db_service: DataService, logger: Optional[logging.Logger] = None):
        """
        Initialize DataMapper with database service and logger.
        
        Args:
            db_service: DataService instance for database operations
            logger: Optional logger instance for logging operations
        """
        self.db_service = db_service
        self.logger = logger or logging.getLogger(__name__)
    
    def apply_mapping(
        self, 
        df: pd.DataFrame, 
        mapping_table: str, 
        target_column: str,
        source_mapping_column: str, 
        target_mapping_column: str,
        df_column: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Apply generic data mapping to a DataFrame column using a database mapping table.
        
        Args:
            df: DataFrame to modify
            mapping_table: Name of the database table containing mappings
            target_column: Column name in df to modify
            source_mapping_column: Column in mapping table that matches df values
            target_mapping_column: Column in mapping table with desired values
            df_column: Column in df to use for mapping (defaults to target_column)
        
        Returns:
            Modified DataFrame with mapped values
            
        Example:
            # Map nationality values
            mapper.apply_mapping(
                df=customer_data,
                mapping_table="NationalityMappings", 
                target_column="Nationality",
                source_mapping_column="Nationality",
                target_mapping_column="CrmNationality"
            )
        """
        try:
            # Use target_column as source if df_column not specified
            df_column = df_column or target_column
            
            # Validate input DataFrame has the required column
            if df_column not in df.columns:
                self.logger.warning(f"Column '{df_column}' not found in DataFrame. Skipping mapping.")
                return df.copy()
            
            if df.empty:
                self.logger.warning("DataFrame is empty. Skipping mapping.")
                return df.copy()
            
            # Load mapping table from database
            self.logger.info(f"Loading mapping table '{mapping_table}' for column '{target_column}'")
            mapping_df = self.db_service.load_table_data(table_name=mapping_table)
            
            if mapping_df.empty:
                self.logger.warning(f"Mapping table '{mapping_table}' is empty. No mappings applied.")
                return df.copy()
            
            # Validate mapping table has required columns
            required_cols = [source_mapping_column, target_mapping_column]
            missing_cols = [col for col in required_cols if col not in mapping_df.columns]
            
            if missing_cols:
                self.logger.error(f"Mapping table '{mapping_table}' missing columns: {missing_cols}")
                return df.copy()
            
            # Create a clean copy of the DataFrame
            result_df = df.copy()
            
            # Create mapping dictionary from the mapping table
            mapping_dict = dict(zip(
                mapping_df[source_mapping_column].astype(str).str.strip(),
                mapping_df[target_mapping_column].astype(str).str.strip()
            ))
            
            self.logger.info(f"Created mapping dictionary with {len(mapping_dict)} entries")
            self.logger.debug(f"Mapping dictionary: {mapping_dict}")
            
            # Apply mapping to the target column
            original_values = result_df[df_column].astype(str).str.strip()
            mapped_values = original_values.map(mapping_dict)
            
            # Count mappings applied
            mappings_applied = 0
            unchanged_values = []
            
            for idx, (original, mapped) in enumerate(zip(original_values, mapped_values)):
                if pd.notna(mapped) and mapped != original:
                    result_df.loc[idx, target_column] = mapped
                    mappings_applied += 1
                    self.logger.debug(f"Mapped '{original}' -> '{mapped}' at index {idx}")
                elif pd.isna(mapped):
                    unchanged_values.append(original)
            
            # Log results
            self.logger.info(f"Mapping completed for column '{target_column}':")
            self.logger.info(f"  - Total rows processed: {len(result_df)}")
            self.logger.info(f"  - Mappings applied: {mappings_applied}")
            self.logger.info(f"  - Unchanged values: {len(unchanged_values)}")
            
            if unchanged_values:
                unique_unchanged = list(set(unchanged_values))
                self.logger.warning(f"Values without mappings: {unique_unchanged}")
            
            return result_df
            
        except Exception as e:
            self.logger.error(f"Error applying mapping to column '{target_column}': {str(e)}")
            return df.copy()
    
    def apply_multiple_mappings(
        self, 
        df: pd.DataFrame, 
        mapping_configs: List[Dict[str, Any]]
    ) -> pd.DataFrame:
        """
        Apply multiple mappings to a DataFrame using a list of mapping configurations.
        
        Args:
            df: DataFrame to modify
            mapping_configs: List of mapping configuration dictionaries
            
        Each config dictionary should contain:
            - mapping_table: str - Database table name
            - target_column: str - Column to modify in df  
            - source_mapping_column: str - Column in mapping table matching df values
            - target_mapping_column: str - Column in mapping table with desired values
            - df_column: str (optional) - Column in df to use for mapping
        
        Returns:
            Modified DataFrame with all mappings applied
            
        Example:
            configs = [
                {
                    "mapping_table": "NationalityMappings",
                    "target_column": "Nationality", 
                    "source_mapping_column": "Nationality",
                    "target_mapping_column": "CrmNationality"
                },
                {
                    "mapping_table": "CountryMappings",
                    "target_column": "Country",
                    "source_mapping_column": "CountryName", 
                    "target_mapping_column": "CrmCountryName"
                }
            ]
            mapped_df = mapper.apply_multiple_mappings(df, configs)
        """
        try:
            result_df = df.copy()
            
            self.logger.info(f"Applying {len(mapping_configs)} mappings to DataFrame")
            
            for i, config in enumerate(mapping_configs, 1):
                self.logger.info(f"Applying mapping {i}/{len(mapping_configs)}")
                
                # Validate configuration
                required_keys = ['mapping_table', 'target_column', 'source_mapping_column', 'target_mapping_column']
                missing_keys = [key for key in required_keys if key not in config]
                
                if missing_keys:
                    self.logger.error(f"Mapping config {i} missing required keys: {missing_keys}")
                    continue
                
                # Apply individual mapping
                result_df = self.apply_mapping(
                    df=result_df,
                    mapping_table=config['mapping_table'],
                    target_column=config['target_column'],
                    source_mapping_column=config['source_mapping_column'],
                    target_mapping_column=config['target_mapping_column'],
                    df_column=config.get('df_column')
                )
            
            self.logger.info("All mappings completed successfully")
            return result_df
            
        except Exception as e:
            self.logger.error(f"Error applying multiple mappings: {str(e)}")
            return df.copy()


def create_nationality_mapping_config() -> Dict[str, Any]:
    """
    Create a standard configuration for nationality mapping.
    
    Returns:
        Dictionary with nationality mapping configuration
    """
    return {
        "mapping_table": "NationalityMappings",
        "target_column": "Nationality",
        "source_mapping_column": "Nationality", 
        "target_mapping_column": "CrmNationality"
    }


def apply_nationality_mapping(
    df: pd.DataFrame, 
    db_service: DataService, 
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """
    Convenience function to apply nationality mapping to a DataFrame.
    
    Args:
        df: DataFrame containing customer data with Nationality column
        db_service: DataService instance for database operations
        logger: Optional logger instance
        
    Returns:
        DataFrame with mapped nationality values
        
    Example:
        # Simple nationality mapping
        mapped_df = apply_nationality_mapping(customer_df, db_service, logger)
    """
    mapper = DataMapper(db_service, logger)
    config = create_nationality_mapping_config()
    
    return mapper.apply_mapping(
        df=df,
        mapping_table=config['mapping_table'],
        target_column=config['target_column'], 
        source_mapping_column=config['source_mapping_column'],
        target_mapping_column=config['target_mapping_column']
    )