from typing import Dict, Any, Optional
import pyodbc
from .constants import SQL_UPDATE_RECORD, SQL_UPDATE_CRM_STATUS, SQL_INSERT_RECORD, TABLE_CUSTOMER

def build_update_query(table_name: str, updates: Dict[str, Any]) -> tuple:
    """
    Build SQL update query and parameters.
    Handles SQL functions (like GETUTCDATE()) by inserting them directly into the query.
    Returns tuple of (query, params)
    """
    set_clauses = []
    params = []
    
    for col, value in updates.items():
        # Check if value is a SQL function (ends with parentheses)
        if isinstance(value, str) and value.endswith('()'):
            # Insert SQL function directly into query
            set_clauses.append(f"{col} = {value}")
        else:
            # Use parameter placeholder for regular values
            set_clauses.append(f"{col} = ?")
            params.append(value)
    
    set_statement = ", ".join(set_clauses)
    
    # Use RequestId for Customers table, Id for other tables
    id_field = "RequestId" if table_name == TABLE_CUSTOMER else "Id"
    query = f"""
    UPDATE {table_name}
    SET {set_statement}
    WHERE {id_field} = ?
    """
    return query, params

def execute_update(
    cursor: pyodbc.Cursor,
    query: str,
    params: list,
    record_id: str
) -> bool:
    """Execute update query with parameters"""
    try:
        all_params = params + [record_id]
        cursor.execute(query, all_params)
        cursor.connection.commit()
        return True
    except Exception as e:
        cursor.connection.rollback()
        raise Exception(f"Update execution failed: {str(e)}")

def update_crm_status(
    cursor: pyodbc.Cursor,
    record_id: str,
    status: str = "Pending"
) -> bool:
    """Update CRM status for a specific record"""
    try:
        cursor.execute(SQL_UPDATE_CRM_STATUS, [status, record_id])
        cursor.connection.commit()
        return True
    except Exception as e:
        cursor.connection.rollback()
        raise Exception(f"CRM status update failed: {str(e)}")

def build_insert_query(table_name: str, data: Dict[str, Any]) -> tuple:
    """
    Build SQL insert query and parameters
    Returns tuple of (query, params)
    """
    columns = list(data.keys())
    values = ['?' for _ in columns]
    
    query = SQL_INSERT_RECORD.format(
        table_name=table_name,
        columns=', '.join(columns),
        values=', '.join(values)
    )
    return query, list(data.values())

def execute_insert(
    cursor: pyodbc.Cursor,
    query: str,
    params: list
) -> bool:
    """Execute insert query with parameters"""
    try:
        cursor.execute(query, params)
        cursor.connection.commit()
        inserted_id = cursor.execute("SELECT @@IDENTITY").fetchone()[0]
        return True, inserted_id
    except Exception as e:
        cursor.connection.rollback()
        raise Exception(f"Insert execution failed: {str(e)}")

def insert_record(
    cursor: pyodbc.Cursor,
    table_name: str,
    data: Dict[str, Any]
) -> tuple[bool, Optional[int]]:
    """
    Insert a new record into specified table
    Returns tuple of (success: bool, inserted_id: Optional[int])
    """
    try:
        query, params = build_insert_query(table_name, data)
        return execute_insert(cursor, query, params)
    except Exception as e:
        raise Exception(f"Record insertion failed: {str(e)}")
