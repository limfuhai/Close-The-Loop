import React, { useRef, useState } from 'react';
import { FileText, Trash2 } from 'lucide-react';
import useStore from '../lib/store';

const ProjectFiles = ({ projectId }) => {
  const fileInputRef = useRef(null);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  
  const { 
    getProjectFiles, 
    addProjectFiles, 
    removeProjectFile,
    addError,
    sendWebSocketMessage
  } = useStore();

  const projectFiles = getProjectFiles(projectId);

  const handleFileUpload = async (event) => {
    const files = Array.from(event.target.files || []);
    if (files.length === 0) return;
  
    setUploadingFiles(true);
    try {
      // Use the uploadProjectFiles function from the store
      const uploadedFiles = await Promise.all(
        files.map(async (file) => {
          // Create FormData
          const formData = new FormData();
          formData.append('file', file);
          formData.append('entityId', projectId);
          formData.append('entityType', 'project');
          
          // Get the HTTP port (WebSocket port + 2)
          const wsPort = window.location.port === '3000' ? '8768' : '8767';
          const httpPort = parseInt(wsPort) + 2;
          
          // Create the upload URL
          const uploadUrl = `${process.env.NEXT_PUBLIC_API_URL}/api/upload`;
          
          // Send the request
          const response = await fetch(uploadUrl, {
            method: 'POST',
            body: formData,
          });
          
          const result = await response.json();
          
          if (!result.success) {
            throw new Error(result.error || 'Upload failed');
          }
          
          return result.file;
        })
      );
  
      // Add to store
      addProjectFiles(projectId, uploadedFiles);
      
    } catch (error) {
      console.error('Failed to upload files:', error);
      addError({
        message: 'Failed to upload files: ' + error.message,
        timestamp: new Date().toISOString()
      });
    } finally {
      setUploadingFiles(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };
  
  const handleFileDelete = async (fileId) => {
    try {
      await removeProjectFile(projectId, fileId);
    } catch (error) {
      addError({
        message: 'Failed to delete file',
        timestamp: new Date().toISOString()
      });
    }
  };

  return (
    <div className="border rounded-lg p-4 bg-white">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Project Files</h3>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            style={{ display: 'none' }}
            onChange={handleFileUpload}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-3 py-1.5 border rounded hover:bg-gray-50"
            disabled={uploadingFiles}
          >
            Add Files
          </button>
          <span className="text-sm text-gray-500">
            {uploadingFiles ? 'Uploading...' : `${projectFiles.length} file(s)`}
          </span>
        </div>
      </div>

      <div className="space-y-2">
        {projectFiles.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            No files uploaded yet
          </div>
        ) : (
          projectFiles.map(file => (
            <div 
              key={file.id} 
              className="flex items-center justify-between p-3 border rounded-lg hover:bg-gray-50"
            >
              <div className="flex items-center gap-3">
                <FileText size={20} className="text-gray-500" />
                <div>
                  <div className="font-medium">{file.name}</div>
                  <div className="text-sm text-gray-500">
                    Added {new Date(file.uploadedAt).toLocaleDateString()}
                  </div>
                </div>
              </div>
              <button
                onClick={() => handleFileDelete(file.id)}
                className="p-2 text-red-500 hover:bg-red-50 rounded-full"
                title="Delete file"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default ProjectFiles;