from typing import List

# Database Tables
TABLE_CUSTOMER = "Customers"
TABLE_USER_CREDENTIALS = "Credentials"

# CRM Status Values
CRM_STATUS_PENDING = "PENDING"
CRM_STATUS_INPROGRESS = "INPROGRESS"
CRM_STATUS_SUCCESS = "SUCCESS"  # Used instead of COMPLETED
CRM_STATUS_FAILED = "FAILED"

# Required Columns
REQUIRED_CLIENT_COLUMNS: List[str] = ['FirstName', 'LastName']
REQUIRED_CREDENTIAL_COLUMNS: List[str] = ['Username', 'Password']

# SQL Queries - Original query for reference
SQL_GET_NEXT_REQUEST = """
    SELECT TOP 1 RequestId, Priority
    FROM Customers 
    WHERE CRMStatus = 'PENDING'
    AND Priority IN ('H', 'M', 'L')
    AND ValidationStatus = 'SUCCESS'
    AND OcrStatus = 'SUCCESS'
    ORDER BY 
        CASE Priority 
            WHEN 'H' THEN 1
            WHEN 'M' THEN 2
            WHEN 'L' THEN 3
        END,
        RequestId
"""

# Atomic SELECT and UPDATE query for multibot concurrency
SQL_GET_NEXT_REQUEST_ATOMIC = """
    WITH NextRequest AS (
        SELECT TOP 1 RequestId, Priority
        FROM Customers WITH (UPDLOCK, READPAST)
        WHERE CRMStatus = 'PENDING'
        AND Priority IN ('H', 'M', 'L')
        AND ValidationStatus = 'SUCCESS'
        AND OcrStatus = 'SUCCESS'
        ORDER BY 
            CASE Priority 
                WHEN 'H' THEN 1
                WHEN 'M' THEN 2
                WHEN 'L' THEN 3
            END,
            RequestId
    )
    UPDATE Customers 
    SET CRMStatus = 'INPROGRESS',
        ProcessingStartedAt = GETUTCDATE(),
        ProcessedByBotId = ?
    OUTPUT inserted.RequestId, inserted.Priority
    FROM Customers c
    INNER JOIN NextRequest nr ON c.RequestId = nr.RequestId
    WHERE c.CRMStatus = 'PENDING'
"""

# Query to find and reset stuck/abandoned requests
SQL_RESET_STUCK_REQUESTS = """
    UPDATE Customers 
    SET CRMStatus = 'PENDING',
        ProcessedByBotId = NULL,
        ProcessingStartedAt = NULL,
        LastError = 'Reset from stuck INPROGRESS state - Bot may have crashed'
    WHERE CRMStatus = 'INPROGRESS' 
    AND ProcessingStartedAt < DATEADD(HOUR, -2, GETUTCDATE())
    AND Priority IN ('H', 'M', 'L')
    AND ValidationStatus = 'SUCCESS'
    AND OcrStatus = 'SUCCESS'
"""

SQL_GET_CREDENTIALS = """
    SELECT Username, Password
    FROM Credentials
    WHERE BotId = ? 
    AND RequestType = ? 
    AND Portal = ? 
    AND IsActive = 1
"""

# SQL Update Queries
SQL_UPDATE_RECORD = """
    UPDATE {table_name}
    SET {set_statement}
    WHERE RequestId = ?
"""

SQL_UPDATE_CRM_STATUS = """
    UPDATE Customers
    SET CRMStatus = ?
    WHERE RequestId = ?
"""

# SQL Insert Query
SQL_INSERT_RECORD = """
    INSERT INTO {table_name} ({columns})
    VALUES ({values})
"""

# SQL Filter Queries
SQL_GET_BY_ID = """
    SELECT * 
    FROM {table_name} 
    WHERE RequestId = ?
"""

SQL_GET_REQUEST_BY_ID = """
    SELECT TOP 1 RequestId 
    FROM Customers 
    WHERE RequestId = ? AND CRMStatus = 'PENDING'
"""

SQL_GET_REQUESTS_BY_STATUS = """
    SELECT RequestId 
    FROM Customers 
    WHERE CRMStatus = ?
    ORDER BY RequestId
"""

SQL_GET_REQUESTS_BY_DATE = """
    SELECT RequestId 
    FROM Customers 
    WHERE CreateDate BETWEEN ? AND ?
    ORDER BY CreateDate
"""

SQL_GET_REQUESTS_BY_PRIORITY = """
    SELECT RequestId 
    FROM Customers 
    WHERE Priority = ?
    ORDER BY RequestId
"""

# SQL Query for Documents
SQL_GET_DOCUMENTS_BY_REQUEST_ID = """
    SELECT DocumentId, RequestId, DocumentType, BlobUrl, BlobContainer, 
           BlobPath, FileName, ContentType, FileSizeBytes, UploadedAt
    FROM ProcessedDocument
    WHERE RequestId = ? 
    AND IsDeleted = 0
    ORDER BY UploadedAt
"""
