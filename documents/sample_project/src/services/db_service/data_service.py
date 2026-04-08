import pandas as pd
from typing import List, Optional, Dict, Any, Callable, TypeVar
from .azure_db_connection import AzureDBConnection
from .constants import *
from .db_utils import build_update_query, execute_update, update_crm_status
import logging
from pathlib import Path
import time
from contextlib import contextmanager
from functools import wraps
import pyodbc

# Type variable for generic return type
T = TypeVar('T')

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 2  # seconds
DEFAULT_RETRY_BACKOFF = 2  # multiplier for exponential backoff


class DatabaseConnectionError(Exception):
    """Custom exception for database connection failures that should trigger retries"""
    pass


def is_connection_error(exception: Exception) -> bool:
    """Check if an exception is a transient database connection error that should be retried"""
    error_str = str(exception).lower()
    
    # Common SQL Server / pyodbc connection error patterns
    connection_error_patterns = [
        'connection',
        'timeout',
        'network',
        'communication link',
        'login failed',
        'server is not found',
        'unable to connect',
        'transport-level error',
        'semaphore timeout',
        'tcp provider',
        'connection was forcibly closed',
        'connection was killed',
        'deadlock',
        '08001',  # SQL Server connection error
        '08s01',  # Communication link failure
        '40001',  # Serialization failure
        '40p01',  # Deadlock detected
    ]
    
    # Check if it's a pyodbc error
    if isinstance(exception, pyodbc.Error):
        return True
    
    # Check error message patterns
    for pattern in connection_error_patterns:
        if pattern in error_str:
            return True
    
    return False

class DataService:
    def __init__(self, run_id: str = None, main_logger=None):
        """
        Initialize DataService with both dedicated db logging and main process logging
        Args:
            run_id: str - Run identifier for log organization
            main_logger: Logger - Main process logger for important DB events
        """
        self.main_logger = main_logger
        self.logger = self._setup_logger(run_id)
        self.db = AzureDBConnection(logger=main_logger)
        self._log_startup_info()

    @contextmanager
    def _db_operation(self):
        """Context manager for database operations"""
        try:
            yield
        finally:
            self.db.close()

    def _retry_db_operation(
        self, 
        operation: Callable[[], T], 
        operation_name: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        backoff: float = DEFAULT_RETRY_BACKOFF
    ) -> T:
        """
        Execute a database operation with retry logic for transient connection errors.
        
        Args:
            operation: Callable that performs the database operation
            operation_name: Name of the operation for logging
            max_retries: Maximum number of retry attempts
            retry_delay: Initial delay between retries in seconds
            backoff: Multiplier for exponential backoff
            
        Returns:
            Result of the operation
            
        Raises:
            DatabaseConnectionError: If all retries are exhausted for a connection error
            Exception: If a non-connection error occurs
        """
        last_exception = None
        current_delay = retry_delay
        
        for attempt in range(max_retries + 1):
            try:
                # Reset the database connection for retry attempts
                if attempt > 0:
                    self._log_info(f"Retry attempt {attempt}/{max_retries} for {operation_name}")
                    # Close existing connection to force reconnection
                    try:
                        self.db.close()
                        self.db = AzureDBConnection(logger=self.main_logger)
                    except Exception:
                        pass  # Ignore errors when resetting connection
                
                return operation()
                
            except Exception as e:
                last_exception = e
                
                # Check if this is a retryable connection error
                if is_connection_error(e):
                    if attempt < max_retries:
                        self._log_error(
                            f"Database connection error in {operation_name} (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {current_delay:.1f} seconds..."
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        self._log_error(
                            f"Database connection error in {operation_name} after {max_retries + 1} attempts: {e}"
                        )
                        raise DatabaseConnectionError(
                            f"Failed to complete {operation_name} after {max_retries + 1} attempts due to connection errors: {e}"
                        )
                else:
                    # Non-connection error - don't retry, just raise
                    self._log_error(f"Non-connection error in {operation_name}: {e}")
                    raise
        
        # Should never reach here, but just in case
        raise last_exception

    def _log_startup_info(self):
        """Log initial startup information"""
        self._log_info("Database service initialized")
        if self.main_logger:
            self._log_db_config()

    def _log_info(self, message: str) -> None:
        """Log to both database log and main process log"""
        self.logger.info(message)
        if self.main_logger:
            self.main_logger.info(f"[Database] {message}")

    def _log_error(self, message: str) -> None:
        """Log errors to both database log and main process log"""
        self.logger.error(message)
        if self.main_logger:
            self.main_logger.error(f"[Database] {message}")

    def _log_db_config(self) -> None:
        """Log database configuration details"""
        config_msg = (
            "Database Configuration:\n"
            f"Server: {self.db.server}\n"
            f"Database: {self.db.database}\n"
            f"Driver: {self.db.driver}"
        )
        self._log_info(config_msg)

    def _setup_logger(self, run_id: Optional[str]) -> logging.Logger:
        """Setup dedicated logger for database operations"""
        logger = logging.getLogger('database_service')
        logger.setLevel(logging.INFO)

        if run_id:
            log_dir = Path(f"data/logs/{run_id}")
            log_dir.mkdir(parents=True, exist_ok=True)
            
            handler = logging.FileHandler(log_dir / 'database.log')
            handler.setLevel(logging.INFO)
            handler.setFormatter(
                logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            )
            logger.addHandler(handler)

        return logger

    def get_next_request_id(self, bot_id: Optional[str] = None) -> Optional[str]:
        """
        Atomically get and reserve the next available request ID from Customer table
        based on priority (H > M > L) where CRMStatus is PENDING.
        Uses atomic UPDATE with OUTPUT to prevent race conditions in multibot scenarios.
        
        Includes retry logic for transient database connection errors.

        Args:
            bot_id: Unique identifier for the bot instance (for tracking and debugging)

        Returns the ID as string, or None if no records found
        
        Raises:
            DatabaseConnectionError: If all retry attempts fail due to connection errors
        """
        # Default bot_id if not provided
        if not bot_id:
            bot_id = f"BOT_{getattr(self, 'run_id', 'UNKNOWN') or 'UNKNOWN'}"

        def _do_get_next_request():
            self._log_info(f"Attempting to atomically reserve next request for bot: {bot_id}")

            with self._db_operation():
                connection = self.db.connect()
                cursor = connection.cursor()

                # Use atomic UPDATE with OUTPUT to select and reserve in one operation
                cursor.execute(SQL_GET_NEXT_REQUEST_ATOMIC, [bot_id])
                result = cursor.fetchone()

                if not result:
                    self._log_info("No available requests found with PENDING CRMStatus")
                    return None

                request_id = str(result[0])
                priority = result[1]

                self._log_info(f"Successfully reserved request ID: {request_id} with Priority: {priority} for bot: {bot_id}")

                # Commit the transaction
                connection.commit()
                cursor.close()

                return request_id

        return self._retry_db_operation(
            operation=_do_get_next_request,
            operation_name=f"get_next_request_id (bot: {bot_id})"
        )

    def reset_stuck_requests(self, max_processing_hours: int = 2) -> int:
        """
        Reset stuck requests that have been in INPROGRESS status for too long.
        Includes retry logic for transient database connection errors.
        
        Args:
            max_processing_hours: Maximum hours a request can be in INPROGRESS before being reset
        Returns:
            Number of requests that were reset
        """
        def _do_reset_stuck():
            self._log_info(f"Attempting to reset stuck requests older than {max_processing_hours} hours")
            
            with self._db_operation():
                cursor = self.db.connect().cursor()
                # Execute the reset query - note: SQL_RESET_STUCK_REQUESTS has hardcoded 2 hours, 
                # but we could modify it to use a parameter if needed
                cursor.execute(SQL_RESET_STUCK_REQUESTS)
                reset_count = cursor.rowcount
                cursor.connection.commit()  # Commit through the connection
                
                if reset_count > 0:
                    self._log_info(f"Successfully reset {reset_count} stuck requests to PENDING status")
                else:
                    self._log_info("No stuck requests found to reset")
                
                return reset_count

        try:
            return self._retry_db_operation(
                operation=_do_reset_stuck,
                operation_name="reset_stuck_requests"
            )
        except DatabaseConnectionError:
            # If retries fail, return 0 and continue - this is not critical
            self._log_error("Failed to reset stuck requests after retries, continuing...")
            return 0

    def _handle_error(self, message: str, error: Exception) -> None:
        """Handle and log errors, re-raising as necessary"""
        error_msg = f"{message}: {str(error)}"
        self._log_error(error_msg)
        raise Exception(error_msg)

    def update_table_record(self, table_name: str, record_id: str, updates: Dict[str, Any]) -> bool:
        """
        Generic method to update any column(s) for a specific record in any table
        Args:
            table_name: str - Name of the table to update
            record_id: str - ID of the record to update
            updates: dict - Dictionary of column names and their new values
        Returns:
            bool - True if update successful
        """
        if not updates:
            self._log_error("No updates provided")
            return False

        try:
            # Log the update attempt with details
            id_field = "RequestId" if table_name == TABLE_CUSTOMER else "Id"
            self._log_info(f"Attempting to update {table_name} where {id_field}={record_id} with: {updates}")
            
            with self._db_operation():
                query, params = build_update_query(table_name, updates)
                self._log_info(f"Generated query: {query}")
                self._log_info(f"Query parameters: {params + [record_id]}")
                
                cursor = self.db.connect().cursor()
                success = execute_update(cursor, query, params, record_id)
                
                if success:
                    # Check how many rows were affected
                    affected_rows = cursor.rowcount
                    self._log_info(f"Successfully updated {table_name} record {record_id} with values: {updates} (affected rows: {affected_rows})")
                    
                    if affected_rows == 0:
                        self._log_error(f"Warning: No rows were updated. Record {record_id} may not exist in {table_name}")
                        return False
                else:
                    self._log_error(f"Update operation returned False for {table_name} record {record_id}")
                    
                return success
                
        except Exception as e:
            self._handle_error(f"Error updating {table_name} record {record_id}", e)
            return False

    def update_crm_status(self, record_id: str, status: str = "INPROGRESS") -> bool:  # Changed default to INPROGRESS
        """
        Update CRMStatus for a specific record.
        Also updates ProcessingCompletedAt timestamp when status is SUCCESS or FAILED.
        """
        try:
            # Build updates dictionary
            updates = {'CRMStatus': status}
            
            # Add ProcessingCompletedAt timestamp when processing completes (SUCCESS or FAILED)
            if status in [CRM_STATUS_SUCCESS, CRM_STATUS_FAILED]:
                updates['ProcessingCompletedAt'] = 'GETUTCDATE()'
                self._log_info(f"Updating CRM status to {status} and recording completion timestamp for record {record_id}")
            else:
                self._log_info(f"Updating CRM status to {status} for record {record_id}")
            
            # Use generic update method to update both fields
            success = self.update_table_record(TABLE_CUSTOMER, record_id, updates)
            
            if success:
                self._log_info(f"Successfully updated CRM status for record {record_id} to {status}")
            else:
                self._log_error(f"Failed to update CRM status for record {record_id} to {status}")
                
            return success
                
        except Exception as e:
            self._handle_error("Error updating CRM status", e)
            return False

    def mark_request_completed(self, request_id: str, bot_id: Optional[str] = None) -> bool:
        """
        Mark a request as completed by updating CRMStatus to SUCCESS and setting completion timestamp.
        
        Args:
            request_id: str - The request ID to mark as completed
            bot_id: str - Bot ID for logging purposes
            
        Returns:
            bool - True if successful
        """
        try:
            bot_info = f" by bot {bot_id}" if bot_id else ""
            self._log_info(f"Marking request {request_id} as completed{bot_info}")
            
            # Update both status and completion timestamp
            updates = {
                'CRMStatus': CRM_STATUS_SUCCESS,
                'ProcessingCompletedAt': 'GETUTCDATE()'  # SQL Server function for current UTC time
            }
            
            success = self.update_table_record(TABLE_CUSTOMER, request_id, updates)
            
            if success:
                self._log_info(f"Successfully marked request {request_id} as completed{bot_info}")
            else:
                self._log_error(f"Failed to mark request {request_id} as completed{bot_info}")
                
            return success
            
        except Exception as e:
            self._handle_error(f"Error marking request {request_id} as completed", e)
            return False

    def release_request_on_failure(self, request_id: str, error_message: Optional[str] = None, bot_id: Optional[str] = None) -> bool:
        """
        Release a request that failed processing by resetting status to PENDING and clearing bot assignment.
        
        Args:
            request_id: str - The request ID to release
            error_message: str - Error message to store
            bot_id: str - Bot ID for logging purposes
            
        Returns:
            bool - True if successful
        """
        try:
            bot_info = f" by bot {bot_id}" if bot_id else ""
            self._log_info(f"Releasing failed request {request_id}{bot_info}")
            
            # Reset status and clear bot assignment
            updates = {
                'CRMStatus': CRM_STATUS_PENDING,
                'ProcessedByBotId': None
            }
            
            # Add error message if provided
            if error_message:
                updates['LastError'] = error_message
            
            success = self.update_table_record(TABLE_CUSTOMER, request_id, updates)
            
            if success:
                self._log_info(f"Successfully released failed request {request_id}{bot_info}")
            else:
                self._log_error(f"Failed to release failed request {request_id}{bot_info}")
                
            return success
            
        except Exception as e:
            self._handle_error(f"Error releasing failed request {request_id}", e)
            return False

    def load_table_data(self, table_name: str, record_id: Optional[int] = None) -> pd.DataFrame:
        """
        Generic function to load data from any table in the database.
        Includes retry logic for transient database connection errors.
        
        Args:
            table_name: str - Name of the table to query
            record_id: Optional[int] - If provided, filters data for specific ID
        Returns:
            DataFrame with original database column names preserved
            
        Raises:
            DatabaseConnectionError: If all retry attempts fail due to connection errors
            ValueError: If no record found with the specified ID
        """
        start_time = time.time()
        self._log_info(f"Starting data load operation from table '{table_name}'")
        
        def _do_load_table_data():
            # Build the query
            if record_id is not None:
                # Use RequestId for Customers table, Id for other tables
                id_field = "RequestId" if table_name == TABLE_CUSTOMER else "Id"
                query = f"SELECT * FROM {table_name} WHERE {id_field} = ?"
                params = [record_id]
                self._log_info(f"Query: Filtering {table_name} for {id_field}: {record_id}")
            else:
                query = f"SELECT * FROM {table_name}"
                params = []
                self._log_info(f"Query: Loading all records from {table_name}")
            
            try:
                # Execute query and get DataFrame
                df = pd.read_sql(query, self.db.connect(), params=params)
                query_time = time.time() - start_time
                
                # Add Priority information to logging if it exists
                if not df.empty and 'Priority' in df.columns:
                    priority = df.iloc[0]['Priority']
                    self._log_info(f"Request Priority: {priority}")
                
                # Log query results
                result_info = (
                    f"Query completed in {query_time:.2f} seconds\n"
                    f"Records retrieved: {len(df)}\n"
                    f"Columns available: {', '.join(df.columns)}"
                )
                self._log_info(result_info)
                
                # Check for empty results
                if len(df) == 0 and record_id is not None:
                    id_field = "RequestId" if table_name == TABLE_CUSTOMER else "Id"
                    error_msg = f"No record found in {table_name} with {id_field}: {record_id}"
                    self._log_error(error_msg)
                    raise ValueError(error_msg)
                elif len(df) == 0:
                    self._log_info(f"Warning: No records found in table {table_name}")
                
                return df
                
            finally:
                try:
                    self.db.close()
                    self._log_info("Database connection closed")
                except Exception as e:
                    self._log_error(f"Error closing database connection: {str(e)}")

        return self._retry_db_operation(
            operation=_do_load_table_data,
            operation_name=f"load_table_data ({table_name}, record_id={record_id})"
        )

    def load_credentials(self, bot_id: str, request_type: str, portal: str) -> pd.DataFrame:
        """
        Load credentials from Azure database with filtering.
        Includes retry logic for transient database connection errors.
        
        Args:
            bot_id: str - Bot identifier from config
            request_type: str - Type of request 
            portal: str - Portal name
        Returns DataFrame with login credentials
        
        Raises:
            DatabaseConnectionError: If all retry attempts fail due to connection errors
            ValueError: If no credentials found or missing required columns
        """
        def _do_load_credentials():
            self._log_info(f"Attempting to load credentials for BotId: {bot_id}, RequestType: {request_type}, Portal: {portal}")
            
            with self._db_operation():
                df = pd.read_sql(SQL_GET_CREDENTIALS, self.db.connect(), params=[bot_id, request_type, portal])
                
                if df.empty:
                    error_msg = f"No active credentials found for BotId: {bot_id}, RequestType: {request_type}, Portal: {portal}"
                    self._log_error(error_msg)
                    raise ValueError(error_msg)
                
                self._log_info(f"Successfully loaded {len(df)} credential record(s)")
                
                # Validate required columns
                required_columns = ['Username', 'Password']
                missing_columns = [col for col in required_columns if col not in df.columns]
                
                if missing_columns:
                    error_msg = f"Missing required columns in credentials: {', '.join(missing_columns)}"
                    self._log_error(error_msg)
                    raise ValueError(error_msg)
                
                return df

        return self._retry_db_operation(
            operation=_do_load_credentials,
            operation_name=f"load_credentials (bot: {bot_id}, type: {request_type}, portal: {portal})"
        )

    def load_documents_by_request_id(self, request_id: str) -> pd.DataFrame:
        """
        Load documents/attachments from Azure database for a specific RequestId
        Args:
            request_id: str - The request ID to load documents for
        Returns DataFrame with document information for blob download
        """
        try:
            self._log_info(f"Attempting to load documents for RequestId: {request_id}")
            
            with self._db_operation():
                df = pd.read_sql(SQL_GET_DOCUMENTS_BY_REQUEST_ID, self.db.connect(), params=[request_id])
                
                if df.empty:
                    self._log_info(f"No documents found for RequestId: {request_id}")
                    return df
                
                self._log_info(f"Successfully loaded {len(df)} document record(s) for RequestId: {request_id}")
                
                # Log document types found
                doc_types = df['DocumentType'].value_counts().to_dict()
                self._log_info(f"Document types found: {doc_types}")
                
                return df

        except Exception as e:
            error_msg = f"Error loading documents from database for RequestId {request_id}: {str(e)}"
            self._log_error(error_msg)
            raise Exception(error_msg)

    def validate_required_columns(self, df: pd.DataFrame, required_cols: List[str], require_any: bool = True) -> bool:
        """
        Validate if DataFrame has required columns
        Uses database column names directly (not JSON names)
        """
        try:
            missing_cols = [col for col in required_cols if col not in df.columns]
            
            if missing_cols:
                if require_any and len(missing_cols) == len(required_cols):
                    error_msg = f"At least one of these columns is required: {', '.join(required_cols)}"
                    self.logger.error(error_msg)
                    raise ValueError(error_msg)
                elif not require_any:
                    error_msg = f"All columns are required: {', '.join(missing_cols)} not found"
                    self.logger.error(error_msg)
                    raise ValueError(error_msg)
            
            return True

        except Exception as e:
            self.logger.error(f"Validation error: {str(e)}")
            raise

    def load_mapping_table(self, table_name: str) -> pd.DataFrame:
        """
        Load a mapping table from the database for data transformation purposes.
        This is a wrapper around load_table_data specifically for mapping operations.
        
        Args:
            table_name: str - Name of the mapping table to load
            
        Returns:
            DataFrame containing the mapping data
            
        Example:
            mapping_df = db_service.load_mapping_table("NationalityMappings")
        """
        try:
            self._log_info(f"Loading mapping table: {table_name}")
            mapping_df = self.load_table_data(table_name=table_name)
            
            if mapping_df.empty:
                self._log_info(f"Warning: Mapping table '{table_name}' is empty")
            else:
                self._log_info(f"Loaded {len(mapping_df)} mapping records from '{table_name}'")
                self._log_info(f"Available mapping columns: {', '.join(mapping_df.columns)}")
            
            return mapping_df
            
        except Exception as e:
            error_msg = f"Error loading mapping table '{table_name}': {str(e)}"
            self._log_error(error_msg)
            raise Exception(error_msg)

    def check_optout_status(self, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Check if a request ID exists in the OptOuts table and return opt-out details if processed.
        
        Args:
            request_id: str - The request ID to check
            
        Returns:
            Dict with opt-out details if Processed=1, None if not found or Processed=0
            Returns: {
                'OptOutId': int,
                'SubmissionId': int,
                'RequestId': int,
                'CustomerEmail': str,
                'CustomerMobile': str,
                'Processed': bool
            }
        """
        try:
            self._log_info(f"Checking OptOuts table for RequestId: {request_id}")
            
            query = """
                SELECT 
                    OptOutId, 
                    SubmissionId, 
                    RequestId, 
                    CustomerEmail, 
                    CustomerMobile, 
                    Processed
                FROM OptOuts 
                WHERE RequestId = ? AND Processed = 1
            """
            
            with self._db_operation():
                df = pd.read_sql(query, self.db.connect(), params=[request_id])
                
                if df.empty:
                    self._log_info(f"No processed opt-out found for RequestId: {request_id}")
                    return None
                
                # Get the first row (should only be one)
                row = df.iloc[0]
                optout_data = {
                    'OptOutId': int(row['OptOutId']),
                    'SubmissionId': int(row['SubmissionId']),
                    'RequestId': int(row['RequestId']),
                    'CustomerEmail': str(row['CustomerEmail']) if pd.notna(row['CustomerEmail']) else None,
                    'CustomerMobile': str(row['CustomerMobile']) if pd.notna(row['CustomerMobile']) else None,
                    'Processed': bool(row['Processed'])
                }
                
                self._log_info(f"Found processed opt-out for RequestId: {request_id} - OptOutId: {optout_data['OptOutId']}")
                return optout_data
                
        except Exception as e:
            error_msg = f"Error checking OptOuts table for RequestId {request_id}: {str(e)}"
            self._log_error(error_msg)
            # Don't raise exception, just return None to allow process to continue
            return None
