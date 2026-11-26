# file_handler.py

import os
import base64
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import uuid

class FileHandler:
    """Handles file upload operations for the OpexAssistant backend"""
    
    def __init__(self, uploads_dir: str = "uploads"):
        """Initialize the file handler with the uploads directory"""
        self.uploads_dir = Path(uploads_dir).resolve()  # Get absolute path
        self.logger = logging.getLogger(__name__)
        
        # Ensure uploads directory exists
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"File handler initialized with uploads directory: {self.uploads_dir}")
    
    async def handle_file_upload(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Process file upload request and save files to the uploads directory"""
        try:
            # Extract file data from payload
            file_data = content.get('fileData')
            file_name = content.get('fileName')
            file_type = content.get('fileType')
            entity_id = content.get('entityId')  # agentId or projectId
            entity_type = content.get('entityType')  # 'agent' or 'project'
            
            if not all([file_data, file_name, entity_id, entity_type]):
                raise ValueError("Missing required file upload parameters")
                
            # Generate a unique filename to prevent collisions
            file_id = str(uuid.uuid4())
            unique_filename = f"{file_id}_{file_name}"
            file_path = self.uploads_dir / unique_filename
            
            # Decode base64 data and save file
            try:
                # Check if the data is base64 encoded
                if ',' in file_data:
                    # Handle data URIs like "data:application/pdf;base64,JVBERi0xLjUKJ..."
                    file_data = file_data.split(',', 1)[1]
                
                # Decode the base64 data
                file_bytes = base64.b64decode(file_data)
                file_path.write_bytes(file_bytes)
                
                self.logger.info(f"File saved: {file_path}")
                
                # Return file metadata
                return {
                    'type': 'FILE_UPLOAD_RESULT',
                    'content': {
                        'success': True,
                        'file': {
                            'id': file_id,  # Use UUID as ID
                            'name': file_name,
                            'path': str(file_path),
                            'size': len(file_bytes),
                            'type': file_type or 'application/octet-stream',
                            'entityId': entity_id,
                            'entityType': entity_type,
                            'uploadedAt': datetime.now().isoformat()
                        },
                        'timestamp': datetime.now().isoformat()
                    }
                }
            except Exception as e:
                self.logger.error(f"Failed to decode and save file: {str(e)}")
                raise ValueError(f"Invalid file data: {str(e)}")
                
        except Exception as e:
            self.logger.error(f"File upload error: {str(e)}")
            return {
                'type': 'FILE_UPLOAD_RESULT',
                'content': {
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }
            }
    
    async def handle_file_upload_batch(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Process multiple file uploads in a single request"""
        try:
            files = content.get('files', [])
            entity_id = content.get('entityId')
            entity_type = content.get('entityType')
            
            if not files:
                raise ValueError("No files provided in batch upload")
                
            results = []
            
            for file_info in files:
                file_content = {
                    'fileData': file_info.get('data'),
                    'fileName': file_info.get('name'),
                    'fileType': file_info.get('type'),
                    'entityId': entity_id,
                    'entityType': entity_type
                }
                
                result = await self.handle_file_upload(file_content)
                if result['content']['success']:
                    results.append(result['content']['file'])
            
            return {
                'type': 'FILE_UPLOAD_BATCH_RESULT',
                'content': {
                    'success': True,
                    'files': results,
                    'timestamp': datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            self.logger.error(f"Batch file upload error: {str(e)}")
            return {
                'type': 'FILE_UPLOAD_BATCH_RESULT',
                'content': {
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }
            }
    
    async def handle_fastapi_upload(self, file: 'UploadFile', entity_id: str, entity_type: str) -> Dict[str, Any]:
        """Process file uploads from FastAPI instead of WebSockets"""
        try:
            # Generate a unique filename to prevent collisions
            file_id = str(uuid.uuid4())
            unique_filename = f"{file_id}_{file.filename}"
            
            # Ensure uploads directory exists (no subdirectories)
            self.uploads_dir.mkdir(parents=True, exist_ok=True)
            
            # Save directly to uploads folder
            file_path = self.uploads_dir / unique_filename
            
            # Stream the file to disk
            with open(file_path, "wb") as buffer:
                contents = await file.read()
                buffer.write(contents)
            
            self.logger.info(f"File saved: {file_path.absolute()}")
            
            # Return file metadata
            file_metadata = {
                'id': file_id,  # Use UUID as ID
                'name': file.filename,
                'path': str(file_path),
                'size': os.path.getsize(file_path),
                'type': file.content_type or 'application/octet-stream',
                'entityId': entity_id,
                'entityType': entity_type,
                'uploadedAt': datetime.now().isoformat()
            }
            
            return {
                'success': True,
                'file': file_metadata
            }
                
        except Exception as e:
            self.logger.error(f"File upload error: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
            
    # Add this method to the FileHandler class in file_handler.py
    async def scan_all_uploads(self) -> List[Dict[str, Any]]:
        """Scan the entire uploads directory and return information about all files"""
        try:
            all_files = []
            uploads_dir = Path(self.uploads_dir)
            if not uploads_dir.exists():
                return []
                
            # Recursively scan all subdirectories
            for file_path in uploads_dir.glob('**/*'):
                if file_path.is_file():
                    # Parse the filename to extract ID and original name
                    try:
                        file_id = file_path.stem.split('_')[0]
                        original_name = '_'.join(file_path.name.split('_')[1:])
                    except IndexError:
                        # Fallback for files that don't follow our naming convention
                        file_id = file_path.stem
                        original_name = file_path.name
                        
                    stats = file_path.stat()
                    all_files.append({
                        'id': file_id,
                        'name': original_name,
                        'path': str(file_path),
                        'size': stats.st_size,
                        'type': self._guess_content_type(file_path),
                        'uploadedAt': datetime.fromtimestamp(stats.st_mtime).isoformat()
                    })
            
            return all_files
        
        except Exception as e:
            self.logger.error(f"Error scanning uploads directory: {str(e)}")
            return []

    async def list_files(self, entity_id: str, entity_type: str) -> List[Dict[str, Any]]:
        """List all files for a specific entity"""
        try:
            entity_dir = self.uploads_dir / entity_type / entity_id
            if not entity_dir.exists():
                return []
            
            files = []
            for file_path in entity_dir.iterdir():
                if file_path.is_file():
                    stats = file_path.stat()
                    files.append({
                        'id': file_path.stem.split('_')[0],  # Extract timestamp as ID
                        'name': '_'.join(file_path.name.split('_')[1:]),  # Remove timestamp
                        'path': str(file_path),
                        'size': stats.st_size,
                        'type': self._guess_content_type(file_path),
                        'entityId': entity_id,
                        'entityType': entity_type,
                        'uploadedAt': datetime.fromtimestamp(stats.st_mtime).isoformat()
                    })
            
            return files
        
        except Exception as e:
            self.logger.error(f"Error listing files: {str(e)}")
            return []
            
    async def list_all_files(self) -> List[Dict[str, Any]]:
        """List all files in the uploads directory regardless of entity"""
        try:
            files = []
            for file_path in self.uploads_dir.iterdir():
                if file_path.is_file():
                    # Parse the filename - first part is UUID, rest is original name
                    parts = file_path.name.split('_', 1)
                    file_id = parts[0]
                    original_name = parts[1] if len(parts) > 1 else file_path.name
                    
                    stats = file_path.stat()
                    files.append({
                        'id': file_id,
                        'name': original_name,
                        'path': str(file_path),
                        'size': stats.st_size,
                        'type': self._guess_content_type(file_path),
                        'uploadedAt': datetime.fromtimestamp(stats.st_mtime).isoformat()
                    })
            
            return files
        
        except Exception as e:
            self.logger.error(f"Error listing all files: {str(e)}")
            return []
    def _guess_content_type(self, file_path: Path) -> str:
        """Guess content type based on file extension"""
        import mimetypes
        return mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'