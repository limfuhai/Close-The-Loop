import { FunctionErrorBoundary } from '@/components/ErrorBoundaries';
import React, { useState } from 'react';
import useStore from '../lib/store';
import ProjectDetailsModal from './ProjectDetailsModal';
import ProjectAgentList from './ProjectAgentList';
import ProjectFiles from './ProjectFiles';
import ProjectGroupChat from './ProjectGroupChat';
import { Plus, Edit2, Trash2, ChevronDown, ChevronUp, MessageCircle } from 'lucide-react';

const ProjectsTab = ({ onEdit = () => {}, activeAgents = [], deactivatedAgents = [] }) => {
  // State management for all our modals and UI controls
  const { 
    projects, 
    setProjects,
    addError
  } = useStore();
  
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingProject, setEditingProject] = useState(null);
  const [expandedProject, setExpandedProject] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(null);
  const [openGroupChat, setOpenGroupChat] = useState(null);

  const handleCreateProject = (data) => {
    try {
      const newProject = {
        id: Date.now().toString(),
        name: data.name,
        description: data.description,
        agents: [],
        dateCreated: new Date().toISOString()
      };

      setProjects([...projects, newProject]);
      setShowCreateModal(false);
    } catch (error) {
      addError({
        message: 'Failed to create project',
        timestamp: new Date().toISOString()
      });
    }
  };

  const handleUpdateProject = (projectId, updates) => {
    try {
      setProjects(projects.map(p => 
        p.id === projectId 
          ? { ...p, ...updates, lastModified: new Date().toISOString() }
          : p
      ));
      setEditingProject(null);
    } catch (error) {
      addError({
        message: 'Failed to update project',
        timestamp: new Date().toISOString()
      });
    }
  };

  const handleDeleteProject = (projectId) => {
    try {
      const project = projects.find(p => p.id === projectId);
      if (project.agents?.length > 0) {
        if (!window.confirm(
          `This project has ${project.agents.length} agents. These agents will be unassigned but not deleted. Continue?`
        )) {
          return;
        }
      }
      
      if (editingProject?.id === projectId) {
        setEditingProject(null);
      }
      
      setProjects(projects.filter(p => p.id !== projectId));
      setShowDeleteConfirm(null);
    } catch (error) {
      addError({
        message: 'Failed to delete project',
        timestamp: new Date().toISOString()
      });
    }
  };

  const getAgentCount = (projectId) => {
    return [...activeAgents, ...deactivatedAgents]
      .filter(agent => agent.project === projectId).length;
  };

  return (
    <FunctionErrorBoundary componentName="Projects Tab">
      <div className="p-6 space-y-6">
        <div className="flex justify-between items-center">
          <h2 className="text-2xl font-bold">Projects</h2>
          <button 
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
          >
            <Plus className="w-4 h-4" />
            Create Project
          </button>
        </div>
  
        <div className="space-y-4">
          {projects.map(project => (
            <FunctionErrorBoundary key={project.id} componentName={`Project Card: ${project.name}`}>
              <div className="border rounded-lg bg-white shadow-sm hover:shadow-md transition-shadow">
                <div className="p-4">
                  <div className="flex justify-between">
                    <div className="flex-grow">
                      <h3 className="text-xl font-bold">{project.name}</h3>
                      <p className="text-gray-600 mt-1">{project.description}</p>
                      <p className="text-sm text-gray-500 mt-2">
                        {getAgentCount(project.id)} Agents
                      </p>
                    </div>
                    
                    <div className="flex gap-2">
                      <button 
                        onClick={() => setEditingProject(project)}
                        className="p-2 text-blue-500 hover:bg-blue-50 rounded-full"
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setShowDeleteConfirm(project.id)}
                        className="p-2 text-red-500 hover:bg-red-50 rounded-full"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setOpenGroupChat(project)}
                        className="p-2 text-blue-500 hover:bg-blue-50 rounded-full"
                        title="Group Chats"
                      >
                        <MessageCircle className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setExpandedProject(
                          expandedProject === project.id ? null : project.id
                        )}
                        className="p-2 text-gray-500 hover:bg-gray-50 rounded-full"
                      >
                        {expandedProject === project.id 
                          ? <ChevronUp className="w-4 h-4" />
                          : <ChevronDown className="w-4 h-4" />
                        }
                      </button>
                    </div>
                  </div>
  
                  {expandedProject === project.id && (
                    <div className="mt-4 border-t pt-4 space-y-4">
                      <FunctionErrorBoundary componentName={`Project Files: ${project.name}`}>
                        <ProjectFiles projectId={project.id} />
                      </FunctionErrorBoundary>
                      <FunctionErrorBoundary componentName={`Project Agents: ${project.name}`}>
                        <ProjectAgentList projectId={project.id} />
                      </FunctionErrorBoundary>
                    </div>
                  )}
                </div>
              </div>
            </FunctionErrorBoundary>
          ))}
        </div>
  
        {/* Modals with error boundaries */}
        {(showCreateModal || editingProject) && (
          <FunctionErrorBoundary componentName="Project Details Modal">
            <ProjectDetailsModal
              project={editingProject}
              onClose={() => {
                setShowCreateModal(false);
                setEditingProject(null);
              }}
              onSave={editingProject ? handleUpdateProject : handleCreateProject}
            />
          </FunctionErrorBoundary>
        )}
  
        {showDeleteConfirm && (
          <FunctionErrorBoundary componentName="Delete Confirmation Modal">
            <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
              <div className="bg-white p-6 rounded-lg max-w-md">
                <h3 className="text-xl font-bold mb-4">Delete project？</h3>
                <p className="text-gray-600 mb-6">
                  Are you sure you want to delete this project? This action cannot be undone.
                </p>
                <div className="flex justify-end gap-4">
                  <button
                    onClick={() => setShowDeleteConfirm(null)}
                    className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => handleDeleteProject(showDeleteConfirm)}
                    className="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          </FunctionErrorBoundary>
        )}
        {openGroupChat && (
          <FunctionErrorBoundary componentName="Project Group Chat Modal">
            <ProjectGroupChat
              project={openGroupChat}
              onClose={() => setOpenGroupChat(null)}
            />
          </FunctionErrorBoundary>
        )}
      </div>
    </FunctionErrorBoundary>
  );}

export default ProjectsTab;