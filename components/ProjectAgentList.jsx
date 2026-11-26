import React, { useState, useMemo } from 'react';
import useStore from '../lib/store';
import { ChevronDown, Plus, X } from 'lucide-react';

const ProjectAgentList = ({ projectId }) => {
  const [showSortMenu, setShowSortMenu] = useState(false);
  const [isAddingAgent, setIsAddingAgent] = useState(false);
  const [showConfirmRemove, setShowConfirmRemove] = useState(null);
  const [sortOrder, setSortOrder] = useState('alphabetical');

  const { 
    activeAgents, 
    deactivatedAgents, 
    updateAgent,
    addError 
  } = useStore();

  const unassignedAgents = useMemo(() => {
    return [...activeAgents, ...deactivatedAgents]
      .filter(agent => !agent.project);
  }, [activeAgents, deactivatedAgents]);

  const projectAgents = useMemo(() => {
    const allAgents = [...activeAgents, ...deactivatedAgents]
      .filter(agent => agent.project === projectId);

    switch (sortOrder) {
      case 'alphabetical':
        return [...allAgents].sort((a, b) => a.name.localeCompare(b.name));
      case 'reverseAlphabetical':
        return [...allAgents].sort((a, b) => b.name.localeCompare(a.name));
      case 'newest':
        return [...allAgents].sort((a, b) => 
          new Date(a.dateCreated).getTime() - new Date(b.dateCreated).getTime()
        ).reverse();
      case 'oldest':
        return [...allAgents].sort((a, b) => 
          new Date(a.dateCreated).getTime() - new Date(b.dateCreated).getTime()
        );
      default:
        return allAgents;
    }
  }, [activeAgents, deactivatedAgents, projectId, sortOrder]);

  const handleAssignAgent = async (agentId) => {
    try {
      await updateAgent(agentId, { project: projectId });
      setIsAddingAgent(false);
    } catch (error) {
      addError({
        message: 'Failed to assign agent to project',
        timestamp: new Date().toISOString()
      });
    }
  };

  const handleRemoveAgent = async (agentId) => {
    try {
      await updateAgent(agentId, { project: null });
      setShowConfirmRemove(null);
    } catch (error) {
      addError({
        message: 'Failed to remove agent from project',
        timestamp: new Date().toISOString()
      });
    }
  };

  const sortOptions = [
    { id: 'alphabetical', label: 'A to Z' },
    { id: 'reverseAlphabetical', label: 'Z to A' },
    { id: 'newest', label: 'Newest First' },
    { id: 'oldest', label: 'Oldest First' }
  ];

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center mb-4">
        <div className="relative">
          <button
            onClick={() => setShowSortMenu(!showSortMenu)}
            className="inline-flex items-center text-sm px-3 py-1.5 border rounded hover:bg-gray-50 gap-1"
          >
            Sort by: {sortOptions.find(opt => opt.id === sortOrder)?.label}
            <ChevronDown className={`w-4 h-4 transition-transform ${showSortMenu ? 'rotate-180' : ''}`} />
          </button>
          
          {showSortMenu && (
            <div className="absolute top-full left-0 mt-1 w-48 bg-white border rounded-lg shadow-lg z-10">
              {sortOptions.map(option => (
                <button
                  key={option.id}
                  onClick={() => {
                    setSortOrder(option.id);
                    setShowSortMenu(false);
                  }}
                  className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-50 ${
                    sortOrder === option.id ? 'bg-blue-50 text-blue-600' : ''
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          onClick={() => setIsAddingAgent(true)}
          className="inline-flex items-center text-sm px-3 py-1.5 bg-blue-500 text-white rounded hover:bg-blue-600 gap-1"
        >
          <Plus className="w-4 h-4" />
          Add Agent
        </button>
      </div>

      <div className="space-y-3">
        {projectAgents.map(agent => (
          <div key={agent.id} className="border rounded-lg p-4 bg-white">
            <div className="flex justify-between items-start">
              <div>
                <h3 className="font-semibold text-lg">{agent.name}</h3>
              </div>
              <button
                onClick={() => setShowConfirmRemove(agent.id)}
                className="text-red-500 hover:text-red-700"
                title="Remove from project"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>

      {isAddingAgent && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-semibold">Add Agent to Project</h3>
              <button
                onClick={() => setIsAddingAgent(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <div className="max-h-96 overflow-y-auto">
              {unassignedAgents.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  No unassigned agents available
                </div>
              ) : (
                unassignedAgents.map(agent => (
                  <div
                    key={agent.id}
                    className="border rounded-lg p-4 mb-2 hover:bg-gray-50 cursor-pointer"
                    onClick={() => handleAssignAgent(agent.id)}
                  >
                    <div className="font-semibold">{agent.name}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {showConfirmRemove && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md">
            <h3 className="text-lg font-semibold mb-4">Remove Agent from Project?</h3>
            <p className="text-gray-600 mb-6">
              The agent will not be deleted, only removed from this project.
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowConfirmRemove(null)}
                className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded"
              >
                Cancel
              </button>
              <button
                onClick={() => handleRemoveAgent(showConfirmRemove)}
                className="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600"
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectAgentList;