"""
CSV Backup Utility for Azure Blob Storage

This module provides automatic backup and restore of CSV files to/from Azure Blob Storage.
It ensures CSV files are not lost in Azure App Service's ephemeral storage.

Usage:
    - Set environment variables for Azure Blob Storage (optional)
    - CSV files are automatically backed up when written
    - CSV files are automatically restored from Blob Storage if local file is missing
"""

import os
from pathlib import Path
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Try to import Azure Blob Storage (optional dependency)
try:
    from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
    AZURE_BLOB_AVAILABLE = True
except ImportError:
    AZURE_BLOB_AVAILABLE = False
    logger.debug("Azure Blob Storage SDK not available. CSV backup will be disabled.")


class CSVBackupManager:
    """Manages CSV file backup to Azure Blob Storage"""
    
    def __init__(self):
        self.enabled = False
        self.blob_service_client: Optional[BlobServiceClient] = None
        self.container_name = "csv-backups"
        self._initialize()
    
    def _initialize(self):
        """Initialize Azure Blob Storage connection if configured"""
        if not AZURE_BLOB_AVAILABLE:
            logger.debug("Azure Blob Storage SDK not installed. Install with: pip install azure-storage-blob")
            return
        
        # Get Azure Blob Storage connection string from environment
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            logger.debug("AZURE_STORAGE_CONNECTION_STRING not set. CSV backup disabled.")
            return
        
        try:
            self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            # Ensure container exists
            self._ensure_container_exists()
            self.enabled = True
            logger.info("✅ CSV backup to Azure Blob Storage enabled")
        except Exception as e:
            logger.warning(f"Failed to initialize Azure Blob Storage: {e}. CSV backup disabled.")
    
    def _ensure_container_exists(self):
        """Ensure the blob container exists"""
        if not self.blob_service_client:
            return
        
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            if not container_client.exists():
                container_client.create_container()
                logger.info(f"Created Azure Blob Storage container: {self.container_name}")
        except Exception as e:
            logger.warning(f"Error ensuring container exists: {e}")
    
    def backup_csv(self, file_path: Path) -> bool:
        """
        Backup a CSV file to Azure Blob Storage
        
        Args:
            file_path: Path to the CSV file to backup
            
        Returns:
            True if backup successful, False otherwise
        """
        if not self.enabled or not file_path.exists():
            return False
        
        try:
            # Create blob name: preserve directory structure
            # e.g., data/live_trader/live_trades_2025-12-24.csv
            blob_name = str(file_path).replace("\\", "/")  # Normalize path separators
            
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            
            # Upload file
            with open(file_path, "rb") as data:
                blob_client.upload_blob(data, overwrite=True)
            
            logger.debug(f"✅ Backed up CSV to Azure Blob Storage: {blob_name}")
            return True
        except Exception as e:
            logger.warning(f"Failed to backup CSV {file_path} to Azure Blob Storage: {e}")
            return False
    
    def restore_csv(self, file_path: Path) -> bool:
        """
        Restore a CSV file from Azure Blob Storage if local file doesn't exist
        
        Args:
            file_path: Path where the CSV file should be restored
            
        Returns:
            True if restore successful, False otherwise
        """
        if not self.enabled or file_path.exists():
            return False
        
        try:
            # Create blob name
            blob_name = str(file_path).replace("\\", "/")
            
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            
            # Check if blob exists
            if not blob_client.exists():
                return False
            
            # Download blob to local file
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(file_path, "wb") as download_file:
                download_file.write(blob_client.download_blob().readall())
            
            logger.info(f"✅ Restored CSV from Azure Blob Storage: {blob_name}")
            return True
        except Exception as e:
            logger.debug(f"CSV not found in Azure Blob Storage or restore failed: {e}")
            return False
    
    def list_backed_up_files(self, prefix: str = "") -> list:
        """
        List all CSV files backed up in Azure Blob Storage
        
        Args:
            prefix: Filter by prefix (e.g., "data/live_trader/")
            
        Returns:
            List of blob names
        """
        if not self.enabled:
            return []
        
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            blobs = container_client.list_blobs(name_starts_with=prefix)
            return [blob.name for blob in blobs]
        except Exception as e:
            logger.warning(f"Error listing backed up files: {e}")
            return []


# Global instance
_csv_backup_manager = None


def get_csv_backup_manager() -> CSVBackupManager:
    """Get the global CSV backup manager instance"""
    global _csv_backup_manager
    if _csv_backup_manager is None:
        _csv_backup_manager = CSVBackupManager()
    return _csv_backup_manager


def backup_csv_file(file_path: Path) -> bool:
    """
    Convenience function to backup a CSV file
    
    Args:
        file_path: Path to the CSV file
        
    Returns:
        True if backup successful, False otherwise
    """
    manager = get_csv_backup_manager()
    return manager.backup_csv(file_path)


def restore_csv_file(file_path: Path) -> bool:
    """
    Convenience function to restore a CSV file from backup
    
    Args:
        file_path: Path where the CSV file should be restored
        
    Returns:
        True if restore successful, False otherwise
    """
    manager = get_csv_backup_manager()
    return manager.restore_csv(file_path)

