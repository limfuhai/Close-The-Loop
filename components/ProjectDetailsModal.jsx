import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';

const ProjectDetailsModal = ({ project = null, onClose, onSave }) => {
  const [formData, setFormData] = useState({
    name: '',
    description: ''
  });
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  useEffect(() => {
    if (project) {
      setFormData({
        name: project.name,
        description: project.description
      });
    }
  }, [project]);
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    
    try {
      if (!formData.name.trim()) {
        throw new Error('Project name is required');
      }
      
      if (project) {
        await onSave(project.id, formData);
      } else {
        await onSave(formData);
      }
      
      onClose();
    } catch (error) {
      console.error('Error saving project:', error);
    } finally {
      setIsSubmitting(false);
    }
  };
  
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-2xl">
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-2xl font-bold">
            {project ? 'Edit Project' : 'Create New Project'}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700"
          >
            <X className="w-6 h-6" />
          </button>
        </div>
        
        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Project Name *
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData(prev => ({ ...prev, name: e.target.value }))}
              className="w-full p-2 border rounded"
              placeholder="Enter project name"
              disabled={isSubmitting}
            />
          </div>
          
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Description
            </label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData(prev => ({ ...prev, description: e.target.value }))}
              className="w-full p-2 border rounded h-32"
              placeholder="Describe the project's purpose and goals"
              disabled={isSubmitting}
            />
          </div>
          
          <div className="flex justify-end gap-4 pt-4 border-t">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 ${
                isSubmitting ? 'opacity-50 cursor-not-allowed' : ''
              }`}
              disabled={isSubmitting}
            >
              {isSubmitting 
                ? 'Saving...' 
                : project 
                  ? 'Save Changes' 
                  : 'Create Project'
              }
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ProjectDetailsModal;