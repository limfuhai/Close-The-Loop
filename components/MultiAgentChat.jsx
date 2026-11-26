import React, { useState, useEffect } from 'react';
import useStore from '../lib/store';
import { 
  Brain, 
  FileText, 
  CheckCircle, 
  AlertCircle, 
  Clock, 
  Users,
  Workflow,
  Target,
  ClipboardCheck,
  Send,
  ChevronRight,
  Loader
} from 'lucide-react';

const MultiAgentChat = ({ projectId }) => {
  const [userInput, setUserInput] = useState('');
  const [selectedOrchestration, setSelectedOrchestration] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  
  const { 
    triggerOrchestrator,
    orchestratorSessions,
    activeAgents,
    projects,
    addError
  } = useStore();
  
  // Get project info
  const project = projects.find(p => p.id === projectId);
  const projectAgents = activeAgents.filter(a => a.projectId === projectId);
  
  // Get orchestration sessions for this project
  const projectOrchestrations = Object.values(orchestratorSessions)
    .filter(o => o.projectId === projectId)
    .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
  
  // Character count for complexity detection
  const COMPLEXITY_THRESHOLD = 500;
  const isComplex = userInput.length > COMPLEXITY_THRESHOLD;
  
  const handleSubmit = async () => {
    if (!userInput.trim()) return;
    
    setIsLoading(true);
    try {
      // For now, use the first agent as the triggering agent
      const triggeringAgent = projectAgents[0];
      if (!triggeringAgent) {
        throw new Error('No agents available in project');
      }
      
      const orchestrationId = await triggerOrchestrator(
        projectId,
        userInput,
        triggeringAgent.id
      );
      
      setSelectedOrchestration(orchestrationId);
      setUserInput('');
    } catch (error) {
      console.error('Failed to trigger orchestrator:', error);
      addError({
        message: 'Failed to start orchestration: ' + error.message,
        timestamp: new Date().toISOString()
      });
    } finally {
      setIsLoading(false);
    }
  };
  
  const getStatusIcon = (status) => {
    switch (status) {
      case 'assessing': return <Brain className="animate-pulse" />;
      case 'dividing_tasks': return <Workflow className="animate-pulse" />;
      case 'providing_context': return <FileText className="animate-pulse" />;
      case 'distributing_tasks': return <Users className="animate-pulse" />;
      case 'tasks_distributed': return <Clock />;
      case 'completed': return <CheckCircle className="text-green-500" />;
      case 'error': return <AlertCircle className="text-red-500" />;
      default: return <Clock />;
    }
  };
  
  const getStatusLabel = (status) => {
    switch (status) {
      case 'assessing': return 'Assessing Project';
      case 'dividing_tasks': return 'Dividing Tasks';
      case 'providing_context': return 'Providing Context';
      case 'distributing_tasks': return 'Distributing to Agents';
      case 'tasks_distributed': return 'Tasks Distributed';
      case 'completed': return 'Completed';
      case 'error': return 'Error';
      default: return status;
    }
  };
  
  const selectedSession = selectedOrchestration 
    ? orchestratorSessions[selectedOrchestration] 
    : null;
  
  return (
    <div className="flex h-full">
      {/* Left Sidebar - Orchestration Sessions */}
      <div className="w-80 bg-gray-50 border-r border-gray-200 flex flex-col">
        <div className="p-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Workflow size={20} />
            Orchestration Sessions
          </h2>
          <p className="text-sm text-gray-600 mt-1">
            Project: {project?.name || 'Unknown'}
          </p>
        </div>
        
        <div className="flex-1 overflow-y-auto">
          {projectOrchestrations.length === 0 ? (
            <div className="p-4 text-center text-gray-500">
              <p>No orchestration sessions yet.</p>
              <p className="text-sm mt-2">
                Submit a complex request (500+ characters) to start orchestration.
              </p>
            </div>
          ) : (
            <div className="p-2 space-y-2">
              {projectOrchestrations.map(session => (
                <button
                  key={session.id}
                  onClick={() => setSelectedOrchestration(session.id)}
                  className={`w-full p-3 rounded-lg text-left transition-colors ${
                    selectedOrchestration === session.id
                      ? 'bg-blue-100 border-blue-300 border'
                      : 'bg-white hover:bg-gray-100 border border-gray-200'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {getStatusIcon(session.status)}
                      <span className="font-medium text-sm">
                        {session.id.slice(-8)}
                      </span>
                    </div>
                    <span className="text-xs text-gray-500">
                      {getStatusLabel(session.status)}
                    </span>
                  </div>
                  <div className="text-xs text-gray-600 mt-1 truncate">
                    {new Date(session.createdAt).toLocaleString()}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
        
        {/* New Request Input */}
        <div className="p-4 border-t border-gray-200">
          <div className="mb-2 flex justify-between items-center">
            <label className="text-sm font-medium">New Complex Request</label>
            <span className={`text-xs ${isComplex ? 'text-green-600' : 'text-gray-500'}`}>
              {userInput.length}/500 chars
            </span>
          </div>
          <textarea
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            placeholder="Describe a complex project that requires multiple agents..."
            className="w-full p-2 border rounded-lg resize-none text-sm"
            rows={4}
            disabled={isLoading}
          />
          <button
            onClick={handleSubmit}
            disabled={!userInput.trim() || isLoading}
            className={`w-full mt-2 py-2 rounded-lg flex items-center justify-center gap-2 ${
              !userInput.trim() || isLoading
                ? 'bg-gray-200 text-gray-400 cursor-not-allowed'
                : isComplex
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'bg-gray-300 text-gray-700 hover:bg-gray-400'
            }`}
          >
            {isLoading ? (
              <>
                <Loader size={16} className="animate-spin" />
                <span>Processing...</span>
              </>
            ) : (
              <>
                <Send size={16} />
                <span>{isComplex ? 'Start Orchestration' : 'Too Simple (Add Detail)'}</span>
              </>
            )}
          </button>
        </div>
      </div>
      
      {/* Right Content - Orchestration Details */}
      <div className="flex-1 bg-white">
        {selectedSession ? (
          <OrchestratorSessionView session={selectedSession} projectAgents={projectAgents} />
        ) : (
          <div className="h-full flex items-center justify-center text-gray-400">
            <div className="text-center">
              <Workflow size={48} className="mx-auto mb-4" />
              <p>Select an orchestration session to view details</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// Component to display orchestration session details
const OrchestratorSessionView = ({ session, projectAgents }) => {
  const phases = [
    { key: 'assessing', label: 'Project Assessment', icon: Brain },
    { key: 'dividing_tasks', label: 'Task Division', icon: Workflow },
    { key: 'providing_context', label: 'Context Provision', icon: FileText },
    { key: 'distributing_tasks', label: 'Task Distribution', icon: Users },
    { key: 'tasks_distributed', label: 'Monitoring Progress', icon: Clock }
  ];
  
  const getCurrentPhaseIndex = () => {
    const index = phases.findIndex(p => p.key === session.status);
    return index >= 0 ? index : phases.length - 1;
  };
  
  const currentPhaseIndex = getCurrentPhaseIndex();
  
  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <h3 className="text-lg font-semibold">Orchestration Session</h3>
        <p className="text-sm text-gray-600">ID: {session.id}</p>
      </div>
      
      {/* Phase Progress */}
      <div className="p-4 bg-gray-50 border-b">
        <div className="flex items-center justify-between">
          {phases.map((phase, index) => {
            const Icon = phase.icon;
            const isActive = index === currentPhaseIndex;
            const isCompleted = index < currentPhaseIndex;
            
            return (
              <React.Fragment key={phase.key}>
                <div className="flex flex-col items-center">
                  <div className={`
                    w-10 h-10 rounded-full flex items-center justify-center
                    ${isCompleted ? 'bg-green-500 text-white' : 
                      isActive ? 'bg-blue-500 text-white animate-pulse' : 
                      'bg-gray-300 text-gray-500'}
                  `}>
                    <Icon size={20} />
                  </div>
                  <span className={`text-xs mt-1 ${isActive ? 'font-semibold' : ''}`}>
                    {phase.label}
                  </span>
                </div>
                {index < phases.length - 1 && (
                  <ChevronRight className="text-gray-400" size={20} />
                )}
              </React.Fragment>
            );
          })}
        </div>
      </div>
      
      {/* Content Area */}
      <div className="flex-1 overflow-y-auto p-4">
        {/* Assessment */}
        {session.assessment && (
          <div className="mb-6">
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <Target size={16} />
              Project Assessment
            </h4>
            <div className="bg-blue-50 p-4 rounded-lg">
              <p className="text-sm mb-2">
                <strong>Overview:</strong> {session.assessment.project_overview}
              </p>
              {session.assessment.key_components && (
                <div className="mt-2">
                  <strong className="text-sm">Key Components:</strong>
                  <ul className="list-disc list-inside text-sm mt-1">
                    {session.assessment.key_components.map((comp, i) => (
                      <li key={i}>{comp}</li>
                    ))}
                  </ul>
                </div>
              )}
              {session.assessment.complexity_score && (
                <p className="text-sm mt-2">
                  <strong>Complexity Score:</strong> {session.assessment.complexity_score}/10
                </p>
              )}
            </div>
          </div>
        )}
        
        {/* Tasks */}
        {session.tasks && session.tasks.length > 0 && (
          <div className="mb-6">
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <ClipboardCheck size={16} />
              Distributed Tasks
            </h4>
            <div className="space-y-3">
              {session.tasks.map((task, index) => {
                const assignedAgent = projectAgents.find(a => a.id === task.assigned_agent_id);
                const taskStatus = session.taskStatus?.[task.task_id] || 'assigned';
                
                return (
                  <div key={task.task_id} className="bg-gray-50 p-4 rounded-lg">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <h5 className="font-medium">{task.task_name}</h5>
                        <p className="text-sm text-gray-600 mt-1">{task.description}</p>
                        {assignedAgent && (
                          <p className="text-xs text-blue-600 mt-2">
                            Assigned to: {assignedAgent.name}
                          </p>
                        )}
                      </div>
                      <TaskStatusBadge status={taskStatus} />
                    </div>
                    {task.is_revision && (
                      <div className="mt-2 p-2 bg-yellow-50 rounded text-sm">
                        <strong>Revision Required:</strong> Quality control feedback provided
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
        
        {/* Error State */}
        {session.status === 'error' && session.error && (
          <div className="bg-red-50 border border-red-200 p-4 rounded-lg">
            <p className="text-red-700">
              <strong>Error:</strong> {session.error}
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

// Helper component for task status badges
const TaskStatusBadge = ({ status }) => {
  const config = {
    assigned: { color: 'bg-gray-200 text-gray-700', label: 'Assigned' },
    in_progress: { color: 'bg-blue-200 text-blue-700', label: 'In Progress' },
    completed: { color: 'bg-green-200 text-green-700', label: 'Completed' },
    needs_revision: { color: 'bg-yellow-200 text-yellow-700', label: 'Needs Revision' },
    completed_with_issues: { color: 'bg-orange-200 text-orange-700', label: 'Completed (Issues)' }
  };
  
  const { color, label } = config[status] || config.assigned;
  
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${color}`}>
      {label}
    </span>
  );
};

export default MultiAgentChat;