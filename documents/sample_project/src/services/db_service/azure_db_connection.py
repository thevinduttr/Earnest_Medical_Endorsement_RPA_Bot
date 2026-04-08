import pyodbc
import pandas as pd
from typing import Optional
from dotenv import load_dotenv
import os

# Load environment variables from db.env
load_dotenv("config/env/db.env")

class AzureDBConnection:
    def __init__(self, logger=None):
        self.server = os.getenv('DB_SERVER')
        self.database = os.getenv('DB_DATABASE')
        self.username = os.getenv('DB_USERNAME')
        self.password = os.getenv('DB_PASSWORD')
        self.driver = os.getenv('DB_DRIVER')
        self.conn: Optional[pyodbc.Connection] = None
        self.logger = logger

    def _log_info(self, message: str):
        """Log info message to both database and main process logs"""
        if self.logger:
            self.logger.info(f"[Database] {message}")

    def _log_error(self, message: str):
        """Log error message to both database and main process logs"""
        if self.logger:
            self.logger.error(f"[Database] {message}")

    def connect(self) -> pyodbc.Connection:
        """Establish connection to Azure SQL Database"""
        try:
            self._log_info(f"Attempting to connect to database '{self.database}' on server '{self.server}'")
            
            connection_string = (
                f'DRIVER={self.driver};'
                f'SERVER={self.server};'
                f'DATABASE={self.database};'
                f'UID={self.username};'
                f'PWD={self.password}'
            )
            self.conn = pyodbc.connect(connection_string)
            
            # Get server version and connection details
            cursor = self.conn.cursor()
            server_info = cursor.execute("SELECT @@VERSION").fetchone()[0]
            cursor.close()
            
            self._log_info(f"Successfully connected to database. Server Info: {server_info.split()[0]}")
            return self.conn
            
        except pyodbc.Error as e:
            error_msg = f"Error connecting to Azure SQL Database: {str(e)}"
            self._log_error(error_msg)
            raise Exception(error_msg)

    def close(self):
        """Close the database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def get_data_by_id(self, id: int, table_name: str) -> pd.DataFrame:
        """
        Fetch data from the specified table by ID and return as DataFrame
        
        Args:
            id (int): The ID to search for
            table_name (str): The name of the table to query
            
        Returns:
            pd.DataFrame: DataFrame containing the query results
        """
        try:
            if not self.conn:
                self.connect()
            
            query = f"SELECT * FROM {table_name} WHERE ID = ?"
            return pd.read_sql(query, self.conn, params=[id])
            
        except Exception as e:
            raise Exception(f"Error fetching data: {str(e)}")
