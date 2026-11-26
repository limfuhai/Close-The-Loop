import React, { useState, useMemo, useEffect } from 'react';
import useStore from '../lib/store';

const AgentProjectSelector = ({ 
  currentProjectId = null, 
  onProjectSelect, 
  agentId = null,
  disabled = false,
  className = '' 
}) => {
  // Access store functionality and state
  const { 
    projects, 
    moveAgentBetweenProjects, 
    addProjectError,
    getAgentProject 
  } = useStore();

  // Local state for handling the selection process
  const [isChanging, setIsChanging] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState(currentProjectId);
  const [showConfirmation, setShowConfirmation] = useState(false);

  // Get current project details for the agent if it exists
  const currentProject = useMemo(() => {
    if (agentId) {
      return getAgentProject(agentId);
    }
    return projects.find(p => p.id === currentProjectId) || null;
  }, [agentId, currentProjectId, projects, getAgentProject]);

  // Update selected project when current project changes
  useEffect(() => {
    setSelectedProjectId(currentProject?.id || null);
  }, [currentProject]);

  // Filter and sort projects for the dropdown
  const availableProjects = useMemo(() => {
    return projects
      .sort((a, b) => a.name.localeCompare(b.name))
      .map(project => ({
        id: project.id,
        name: project.name,
        agentCount: project.agents?.length || 0,
        isCurrentProject: project.id === currentProject?.id
      }));
  }, [projects, currentProject]);

  // Handle project selection change
  const handleProjectChange = async (newProjectId) => {
    setSelectedProjectId(newProjectId);
    
    // If this is just initial assignment (no current project), update immediately
    if (!currentProject) {
      onProjectSelect(newProjectId);
      return;
    }
    
    // If changing existing assignment, show confirmation
    if (newProjectId !== currentProject.id) {
      setShowConfirmation(true);
    }
  };

  // Handle confirmation of project change
  const handleConfirmChange = async () => {
    setIsChanging(true);
    try {
      if (!agentId) {
        // Simple project selection
        onProjectSelect(selectedProjectId);
      } else {
        // Moving agent between projects
        const result = await moveAgentBetweenProjects(
          agentId,
          currentProject.id,
          selectedProjectId
        );
        
        if (!result.success) {
          throw new Error(result.error || 'Failed to change project');
        }
        
        onProjectSelect(selectedProjectId);
      }
    } catch (error) {
      addProjectError({
        message: `Failed to change project: ${error.message}`,
        timestamp: new Date().toISOString()
      });
      // Reset selection on error
      setSelectedProjectId(currentProject.id);
    } finally {
      setIsChanging(false);
      setShowConfirmation(false);
    }
  };

  return (
    <div className={`relative ${className}`}>
      {/* Project Selection Dropdown */}
      <div className="relative">
        <select
          value={selectedProjectId || ''}
          onChange={(e) => handleProjectChange(e.target.value || null)}
          disabled={disabled || isChanging}
          className={`w-full p-2 pr-8 border rounded-lg appearance-none
            ${disabled ? 'bg-gray-100 cursor-not-allowed' : 'bg-white cursor-pointer'}
            focus:ring-2 focus:ring-blue-500 focus:border-blue-500`}
        >
          <option value="">No Project</option>
          {availableProjects.map(project => (
            <option key={project.id} value={project.id}>
              {project.name} ({project.agentCount} agent{project.agentCount !== 1 ? 's' : ''})
              {project.isCurrentProject ? ' (Current)' : ''}
            </option>
          ))}
        </select>
        
        {/* Custom dropdown arrow */}
        <div className="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none">
          <svg 
            className="w-4 h-4 text-gray-400"
            fill="none" 
            stroke="currentColor" 
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 9l-7 7-7-7"
            />
          </svg>
        </div>
      </div>

      {/* Quick create project button */}
      {!disabled && (
        <button
          onClick={() => {/* TODO: Integrate with ProjectDetailsModal */}}
          className="absolute right-0 top-0 -mt-6 text-sm text-blue-500 hover:text-blue-700"
        >
          Create New Project
        </button>
      )}

      {/* Project Change Confirmation Modal */}
      {showConfirmation && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md">
            <h3 className="text-xl font-bold mb-4">Change Project Assignment?</h3>
            <p className="text-gray-600 mb-2">
              Are you sure you want to move this agent from:
            </p>
            <p className="font-medium mb-2">
              {currentProject?.name} → {
                selectedProjectId 
                  ? projects.find(p => p.id === selectedProjectId)?.name 
                  : 'No Project'
              }
            </p>
            <p className="text-gray-600 mb-6">
              will update the agent&apos;s project assignment and may affect ongoing tasks.
            </p>
            <div className="flex justify-end gap-4">
              <button
                onClick={() => {
                  setSelectedProjectId(currentProject.id);
                  setShowConfirmation(false);
                }}
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded"
                disabled={isChanging}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmChange}
                className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600
                  ${isChanging ? 'opacity-50 cursor-not-allowed' : ''}`}
                disabled={isChanging}
              >
                {isChanging ? 'Changing...' : 'Confirm Change'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AgentProjectSelector;