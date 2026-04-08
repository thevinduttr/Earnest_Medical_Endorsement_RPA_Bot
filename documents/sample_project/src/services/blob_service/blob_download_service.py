import os
import logging
from typing import List, Dict, Optional
from pathlib import Path
import pandas as pd
from azure.storage.blob import BlobServiceClient, BlobSasPermissions, generate_blob_sas, UserDelegationKey
from azure.storage.blob._models import BlobProperties
from urllib.parse import urlparse, urlencode
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import requests

# Load environment variables from blob.env file
load_dotenv('config/env/blob.env')

class BlobDownloadService:
    """Service for downloading attachments from Azure Blob Storage"""
    
    def __init__(self, connection_string: str = None, logger: logging.Logger = None):
        """
        Initialize BlobDownloadService
        Args:
            connection_string: Azure Storage connection string
            logger: Logger instance for logging operations
        """
        self.logger = logger or logging.getLogger(__name__)
        self.connection_string = connection_string or self._get_connection_string()
        
        if not self.connection_string:
            raise ValueError("Azure Storage connection string is required")
        
        try:
            self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
            self.logger.info("Azure Blob Service Client initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Azure Blob Service Client: {e}")
            raise
    
    def _get_connection_string(self) -> Optional[str]:
        """Get connection string from environment variables or config"""
        # Try different possible environment variable names
        env_vars = [
            'AZURE_STORAGE_CONNECTION_STRING',
            'BLOB_CONNECTION_STRING',
            'AZURE_BLOB_CONNECTION_STRING'
        ]
        
        for env_var in env_vars:
            connection_string = os.getenv(env_var)
            if connection_string:
                self.logger.info(f"Found connection string in environment variable: {env_var}")
                return connection_string
        
        self.logger.warning("No Azure Storage connection string found in environment variables")
        return None

    def get_sas_uri(self, container_name: str, blob_name: str) -> Optional[str]:
        """
        Generate a SAS URI for accessing a blob with User Delegation Key
        This method handles authentication issues by generating temporary access tokens
        
        Args:
            container_name: Name of the blob container
            blob_name: Name of the blob file
            
        Returns:
            SAS URI string or None if generation fails
        """
        try:
            if not blob_name or not blob_name.strip():
                raise ValueError("Blob name cannot be empty")
            
            # Remove any leading/trailing slashes
            blob_name = blob_name.strip('/')
            
            # Get storage account name from connection string
            storage_account_name = self._extract_account_name_from_connection_string()
            if not storage_account_name:
                self.logger.error("Could not extract storage account name from connection string")
                return None
            
            # Get blob client
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, 
                blob=blob_name
            )
            
            # Try to generate User Delegation Key for 1 hour
            try:
                start_time = datetime.now(timezone.utc)
                expiry_time = start_time + timedelta(hours=1)
                
                delegation_key = self.blob_service_client.get_user_delegation_key(
                    key_start_time=start_time,
                    key_expiry_time=expiry_time
                )
                
                # Generate SAS token with User Delegation Key
                sas_token = generate_blob_sas(
                    account_name=storage_account_name,
                    container_name=container_name,
                    blob_name=blob_name,
                    user_delegation_key=delegation_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.now(timezone.utc) + timedelta(minutes=30)
                )
                
                # Build complete SAS URI
                sas_uri = f"{blob_client.url}?{sas_token}"
                self.logger.debug(f"Generated SAS URI for blob: {container_name}/{blob_name}")
                return sas_uri
                
            except Exception as delegation_error:
                self.logger.warning(f"User Delegation Key generation failed: {delegation_error}")
                # Fallback: try account SAS if account key is available
                return self._generate_account_sas_uri(container_name, blob_name, blob_client.url)
                
        except Exception as e:
            self.logger.error(f"Error generating SAS URI for {container_name}/{blob_name}: {e}")
            return None

    def _extract_account_name_from_connection_string(self) -> Optional[str]:
        """Extract storage account name from connection string"""
        try:
            if not self.connection_string:
                return None
                
            # Parse connection string to find AccountName
            parts = self.connection_string.split(';')
            for part in parts:
                if part.strip().startswith('AccountName='):
                    return part.split('=', 1)[1].strip()
                    
            return None
        except Exception as e:
            self.logger.error(f"Error extracting account name from connection string: {e}")
            return None

    def _generate_account_sas_uri(self, container_name: str, blob_name: str, blob_url: str) -> Optional[str]:
        """
        Fallback method to generate SAS using account key instead of User Delegation Key
        """
        try:
            # Extract account key from connection string
            account_key = self._extract_account_key_from_connection_string()
            storage_account_name = self._extract_account_name_from_connection_string()
            
            if not account_key or not storage_account_name:
                self.logger.warning("Could not extract account key or name for SAS generation")
                return None
            
            # Generate SAS token with account key
            sas_token = generate_blob_sas(
                account_name=storage_account_name,
                container_name=container_name,
                blob_name=blob_name,
                account_key=account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(timezone.utc) + timedelta(minutes=30)
            )
            
            sas_uri = f"{blob_url}?{sas_token}"
            self.logger.debug(f"Generated account SAS URI for blob: {container_name}/{blob_name}")
            return sas_uri
            
        except Exception as e:
            self.logger.error(f"Error generating account SAS URI: {e}")
            return None

    def _extract_account_key_from_connection_string(self) -> Optional[str]:
        """Extract account key from connection string"""
        try:
            if not self.connection_string:
                return None
                
            # Parse connection string to find AccountKey
            parts = self.connection_string.split(';')
            for part in parts:
                if part.strip().startswith('AccountKey='):
                    return part.split('=', 1)[1].strip()
                    
            return None
        except Exception as e:
            self.logger.error(f"Error extracting account key from connection string: {e}")
            return None
    
    def download_request_attachments(self, request_id: str, documents_df: pd.DataFrame, 
                                   download_path: str = "data/attachments") -> Dict[str, List[str]]:
        """
        Download all attachments for a specific request ID
        Args:
            request_id: The request ID to download attachments for
            documents_df: DataFrame containing document information from database
            download_path: Local path to save downloaded files
        Returns:
            Dictionary containing download results and file paths
        """
        self.logger.info(f"Starting attachment download for request ID: {request_id}")
        
        if documents_df.empty:
            self.logger.info(f"No documents found for request ID: {request_id}")
            return {"success": [], "failed": [], "skipped": []}
        
        # Create request-specific directory
        request_dir = Path(download_path) / f"request_{request_id}"
        request_dir.mkdir(parents=True, exist_ok=True)
        
        results = {"success": [], "failed": [], "skipped": []}
        
        for _, document in documents_df.iterrows():
            try:
                file_path = self._download_single_document(document, request_dir)
                if file_path:
                    results["success"].append(str(file_path))
                    self.logger.info(f"Successfully downloaded: {file_path}")
                else:
                    results["skipped"].append(document.get('FileName', 'Unknown'))
            except Exception as e:
                error_msg = f"Failed to download document {document.get('DocumentId', 'Unknown')}: {e}"
                self.logger.error(error_msg)
                results["failed"].append(document.get('FileName', 'Unknown'))
        
        summary = (f"Download completed for request {request_id}. "
                  f"Success: {len(results['success'])}, "
                  f"Failed: {len(results['failed'])}, "
                  f"Skipped: {len(results['skipped'])}")
        self.logger.info(summary)
        
        # Copy downloaded files to main attachments directory for upload processes
        if results["success"]:
            self._copy_files_to_main_directory(results["success"], download_path)
        
        return results
    
    def _copy_files_to_main_directory(self, downloaded_files: List[str], base_path: str) -> None:
        """
        Copy downloaded files from request subdirectory to main attachments directory
        This ensures upload processes can find the files in the expected location
        Args:
            downloaded_files: List of file paths that were successfully downloaded
            base_path: Base download path (e.g., "data/attachments")
        """
        import shutil
        
        try:
            main_dir = Path(base_path)
            main_dir.mkdir(parents=True, exist_ok=True)
            
            for file_path_str in downloaded_files:
                file_path = Path(file_path_str)
                if file_path.exists():
                    destination = main_dir / file_path.name
                    
                    # Copy file to main directory, overwriting if exists
                    shutil.copy2(file_path, destination)
                    self.logger.debug(f"Copied {file_path.name} to main attachments directory")
                    
        except Exception as e:
            self.logger.error(f"Error copying files to main directory: {e}")

        return results
    
    def _download_single_document(self, document: pd.Series, download_dir: Path) -> Optional[Path]:
        """
        Download a single document from blob storage
        Args:
            document: Series containing document information
            download_dir: Directory to save the file
        Returns:
            Path of downloaded file or None if skipped
        """
        try:
            blob_url = document.get('BlobUrl')
            blob_container = document.get('BlobContainer')
            blob_path = document.get('BlobPath')
            original_filename = document.get('FileName')
            document_type = document.get('DocumentType')
            
            if not blob_url and not (blob_container and blob_path):
                self.logger.warning(f"Missing blob information for document {document.get('DocumentId')}")
                return None
            
            # Determine filename with document type or original filename
            filename = self._get_download_filename(document_type, original_filename)
            file_path = download_dir / filename
            
            # Download the blob
            if blob_url:
                # Download using direct URL
                success = self._download_from_url(blob_url, file_path)
            else:
                # Download using container and path
                success = self._download_from_container(blob_container, blob_path, file_path)
            
            return file_path if success else None
            
        except Exception as e:
            self.logger.error(f"Error downloading document {document.get('DocumentId', 'Unknown')}: {e}")
            raise
    
    def _get_download_filename(self, document_type: str, original_filename: str) -> str:
        """
        Generate filename based on document type or original filename
        Args:
            document_type: Type of document (e.g., 'EMIRATES_ID', 'DRIVING_LICENCE')
            original_filename: Original filename from database
        Returns:
            Filename to use for download
        """
        # List of valid document types
        valid_doc_types = [
            'EMIRATES_ID', 'DRIVING_LICENSE', 'MULKIYA', 
            'E_MULKIYA_HYSA', 'VCC', 'PCD_HYSA', 'KAVAK_QUOTATION', 'ALBA_QUOTATION'
        ]
        
        if document_type and document_type.upper() in valid_doc_types:
            # Get file extension from original filename
            if original_filename:
                file_ext = Path(original_filename).suffix
            else:
                file_ext = '.pdf'  # Default extension
            
            return f"{document_type.upper()}{file_ext}"
        else:
            # Use original filename if document type is null or invalid
            return original_filename or "unknown_document.pdf"
    
    def _download_from_url(self, blob_url: str, file_path: Path) -> bool:
        """
        Download blob using direct URL with SAS fallback
        Handles URLs from different storage accounts automatically
        Args:
            blob_url: Direct URL to the blob
            file_path: Local path to save the file
        Returns:
            True if successful, False otherwise
        """
        try:
            # First try direct HTTP download (in case URL already has SAS)
            try:
                self.logger.debug(f"Attempting direct URL download: {blob_url}")
                response = requests.get(blob_url, stream=True, timeout=60)
                response.raise_for_status()
                
                # Write file content
                with open(file_path, "wb") as download_file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            download_file.write(chunk)
                
                self.logger.debug(f"Successfully downloaded via direct URL")
                return True
                
            except Exception as direct_error:
                self.logger.warning(f"Direct URL download failed: {direct_error}")
                
                # Check if URL is from a different storage account
                parsed_url = urlparse(blob_url)
                url_account = self._extract_account_from_url(parsed_url.netloc)
                config_account = self._extract_account_name_from_connection_string()
                
                if url_account and config_account and url_account != config_account:
                    self.logger.warning(f"Storage account mismatch: URL has '{url_account}' but connection string has '{config_account}'")
                    self.logger.info(f"Trying cross-account download with modified URL")
                    
                    # Try to download from the correct storage account
                    return self._download_cross_account(blob_url, file_path, url_account, config_account)
                else:
                    # Parse the URL to extract container and blob name for SAS fallback
                    path_parts = parsed_url.path.lstrip('/').split('/')
                    if len(path_parts) < 2:
                        raise ValueError(f"Invalid blob URL format: {blob_url}")
                    
                    container_name = path_parts[0]
                    blob_name = '/'.join(path_parts[1:])
                    
                    self.logger.info(f"Falling back to SAS method for {container_name}/{blob_name}")
                    return self._download_from_container(container_name, blob_name, file_path)
            
        except Exception as e:
            self.logger.error(f"Error downloading from URL {blob_url}: {e}")
            return False

    def _extract_account_from_url(self, netloc: str) -> Optional[str]:
        """Extract storage account name from URL netloc"""
        try:
            # netloc format: accountname.blob.core.windows.net
            if '.blob.core.windows.net' in netloc:
                return netloc.split('.blob.core.windows.net')[0]
            return None
        except Exception:
            return None

    def _download_cross_account(self, original_url: str, file_path: Path, 
                              url_account: str, config_account: str) -> bool:
        """
        Try to download from a different storage account by modifying the URL
        """
        try:
            # Replace the account name in the URL
            modified_url = original_url.replace(
                f"{url_account}.blob.core.windows.net",
                f"{config_account}.blob.core.windows.net"
            )
            
            self.logger.debug(f"Modified URL from {url_account} to {config_account}: {modified_url}")
            
            # Parse the modified URL for container/blob extraction
            parsed_url = urlparse(modified_url)
            path_parts = parsed_url.path.lstrip('/').split('/')
            if len(path_parts) < 2:
                raise ValueError(f"Invalid modified URL format: {modified_url}")
            
            container_name = path_parts[0]
            blob_name = '/'.join(path_parts[1:])
            
            # Try to download using our configured storage account
            return self._download_from_container(container_name, blob_name, file_path)
            
        except Exception as e:
            self.logger.error(f"Cross-account download failed: {e}")
            return False
    
    def _download_from_container(self, container_name: str, blob_name: str, file_path: Path) -> bool:
        """
        Download blob using container name and blob path
        Uses SAS URI method to handle authentication issues
        Args:
            container_name: Azure Storage container name
            blob_name: Blob path within container
            file_path: Local path to save the file
        Returns:
            True if successful, False otherwise
        """
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, 
                blob=blob_name
            )
            
            # First try direct download
            try:
                # Check if blob exists
                if not blob_client.exists():
                    self.logger.warning(f"Blob does not exist: {container_name}/{blob_name}")
                    return False
                
                # Download the blob directly
                with open(file_path, "wb") as download_file:
                    blob_data = blob_client.download_blob()
                    download_file.write(blob_data.readall())
                
                self.logger.debug(f"Downloaded blob {container_name}/{blob_name} to {file_path}")
                return True
                
            except Exception as direct_error:
                self.logger.warning(f"Direct download failed for {container_name}/{blob_name}: {direct_error}")
                self.logger.info(f"Attempting SAS URI download for {container_name}/{blob_name}")
                
                # Try SAS URI method as fallback
                return self._download_using_sas_uri(container_name, blob_name, file_path)
            
        except Exception as e:
            self.logger.error(f"Error downloading from container {container_name}/{blob_name}: {e}")
            return False

    def _download_using_sas_uri(self, container_name: str, blob_name: str, file_path: Path) -> bool:
        """
        Download blob using SAS URI method (handles authentication issues)
        Args:
            container_name: Azure Storage container name
            blob_name: Blob path within container
            file_path: Local path to save the file
        Returns:
            True if successful, False otherwise
        """
        try:
            # Generate SAS URI
            sas_uri = self.get_sas_uri(container_name, blob_name)
            
            if not sas_uri:
                self.logger.error(f"Could not generate SAS URI for {container_name}/{blob_name}")
                return False
            
            # Download using HTTP request with SAS URI
            self.logger.debug(f"Downloading using SAS URI: {container_name}/{blob_name}")
            
            response = requests.get(sas_uri, stream=True, timeout=60)
            response.raise_for_status()
            
            # Write file content
            with open(file_path, "wb") as download_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        download_file.write(chunk)
            
            self.logger.debug(f"Successfully downloaded via SAS URI: {container_name}/{blob_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error downloading via SAS URI {container_name}/{blob_name}: {e}")
            return False
    
    def cleanup_old_attachments(self, request_id: str, download_path: str = "data/attachments") -> bool:
        """
        Clean up old attachment files for a request before downloading new ones
        Cleans both request-specific directory and main attachments directory
        Args:
            request_id: The request ID
            download_path: Local path where attachments are stored
        Returns:
            True if cleanup successful
        """
        try:
            # Clean request-specific directory
            request_dir = Path(download_path) / f"request_{request_id}"
            
            if request_dir.exists():
                # Remove all files in the request directory
                for file_path in request_dir.glob('*'):
                    if file_path.is_file():
                        file_path.unlink()
                        self.logger.debug(f"Removed old file: {file_path}")
                
                self.logger.info(f"Cleaned up old attachments for request {request_id}")
            
            # Also clean main attachments directory to prevent conflicts
            main_dir = Path(download_path)  
            if main_dir.exists():
                for file_path in main_dir.glob('*'):
                    if file_path.is_file() and file_path.name.upper() in [
                        'EMIRATES_ID.PDF', 'EMIRATES_ID.JPG', 'EMIRATES_ID.JPEG', 'EMIRATES_ID.PNG',
                        'DRIVING_LICENSE.PDF', 'DRIVING_LICENSE.JPG', 'DRIVING_LICENSE.JPEG', 'DRIVING_LICENSE.PNG',
                        'PCD_HYSA.PDF', 'PCD_HYSA.JPG', 'PCD_HYSA.JPEG', 'PCD_HYSA.PNG',
                        'MULKIYA.PDF', 'MULKIYA.JPG', 'MULKIYA.JPEG', 'MULKIYA.PNG',
                        'E_MULKIYA_HYSA.PDF', 'E_MULKIYA_HYSA.JPG', 'E_MULKIYA_HYSA.JPEG', 'E_MULKIYA_HYSA.PNG',
                        'VCC.PDF', 'VCC.JPG', 'VCC.JPEG', 'VCC.PNG',
                        'KAVAK_QUOTATION.PDF', 'KAVAK_QUOTATION.JPG', 'KAVAK_QUOTATION.JPEG', 'KAVAK_QUOTATION.PNG',
                        'ALBA_QUOTATION.PDF', 'ALBA_QUOTATION.JPG', 'ALBA_QUOTATION.JPEG', 'ALBA_QUOTATION.PNG'
                    ]:
                        file_path.unlink()
                        self.logger.debug(f"Removed old main directory file: {file_path}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error cleaning up attachments for request {request_id}: {e}")
            return False