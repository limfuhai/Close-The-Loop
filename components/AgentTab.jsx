import { FunctionErrorBoundary } from "@/components/ErrorBoundaries";
import { FileText, MessageSquare, Paperclip, PenSquare, X } from "lucide-react";
import { useRef, useState } from "react";
import useStore from "../lib/store";

const AgentTab = ({
  onEdit,
  onChat,
  onCreateAgent,
  activeAgents,
  deactivatedAgents,
  projects,
  isProjectsTab,
}) => {
  const fileInputRef = useRef(null);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [useMultiAgent, setUseMultiAgent] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const {
    deleteAgent,
    toggleAgentStatus,
    formState,
    updateFormState,
    resetFormState,
    addError,
    uploadAgentMessageWithFile,
    startMultiAgentTask,
    startMultiAgentTaskWithFiles,
    sendAgentMessage,
    createNewAgent
  } = useStore();

  const handleCreateAgent = async () => {
    if (isCreating) return;
    const { initialPrompt, project } = formState.agentForm;

    if (!initialPrompt) {
      addError({
        message: "Please fill in all required fields",
        timestamp: new Date().toISOString(),
      });
      return;
    }

    setIsCreating(true);
    try {
      const agentId = Date.now().toString();
      // Generate agent name and save to db before creating the agent in the UI
      const agentResponse = await createNewAgent(initialPrompt, {
        id: agentId,
        projectId: project || null,
        preferMultiAgent: useMultiAgent
      });

      const newAgent = {
        id: agentResponse.id || agentId,
        name: agentResponse.name || 'New Agent',
        initialPrompt,
        project: project || null,
        status: "active",
        dateCreated: new Date().toISOString(),
        lastModified: new Date().toISOString(),
        preferMultiAgent: useMultiAgent,
      };

      onCreateAgent(newAgent);

      if (useMultiAgent) {
        if (selectedFiles.length > 0) {
          await startMultiAgentTaskWithFiles(
            initialPrompt,
            selectedFiles,
            newAgent.id,
            undefined,
            undefined
          );
        } else {
          await startMultiAgentTask(initialPrompt, newAgent.id, undefined, undefined);
        }
      } else {
        if (selectedFiles.length > 0) {
          await uploadAgentMessageWithFile(
            newAgent.id,
            initialPrompt,
            selectedFiles[0]
          );
        } else {
          await sendAgentMessage(newAgent.id, initialPrompt, true, "neutral", undefined);
        }
      }

      setSelectedFiles([]);
      resetFormState();
    } catch (error) {
      console.error("Error during agent creation:", error);
      addError({
        message: "Failed to create agent: " + error.message,
        timestamp: new Date().toISOString(),
      });
    } finally {
      setIsCreating(false);
    }
  };

  const handleAgentDelete = async (agentId) => {
    if (window.confirm("Are you sure you want to delete this agent?")) {
      try {
        deleteAgent(agentId);
      } catch (error) {
        addError({
          message: "Failed to delete agent",
          timestamp: new Date().toISOString(),
        });
      }
    }
  };

  const handleRemoveFile = (fileName) => {
    setSelectedFiles((prev) => prev.filter((file) => file.name !== fileName));
  };

  const handleAgentActivation = (agent, activating) => {
    try {
      toggleAgentStatus(agent.id);
    } catch (error) {
      addError({
        message: `Failed to ${activating ? "activate" : "deactivate"} agent`,
        timestamp: new Date().toISOString(),
      });
    }
  };

  // In handleFileUpload function in AgentTab.jsx
  const handleFileUpload = (event) => {
    const files = Array.from(event.target.files || []);
    if (files.length === 0) return;
    setSelectedFiles((prev) => [...prev, ...files]);
  };

  const renderAgentCard = (agent, isActive) => {
    const agentProject = projects.find((p) => p.id === agent.project);

    return (
      <div key={agent.id} className="p-4 bg-white border rounded">
        <div className="flex justify-between">
          <div>
            <div className="font-bold">{agent.name}</div>
            <div className="mt-2 text-sm text-gray-500">
              Project: {agentProject ? agentProject.name : "None"}
            </div>
          </div>
          <div className="flex gap-2">
            {!isProjectsTab && (
              <>
                <button
                  onClick={() => onChat(agent)}
                  className="p-2 text-blue-500 rounded-full hover:text-blue-700 hover:bg-blue-50"
                  title="Chat with agent"
                >
                  <MessageSquare size={20} />
                </button>
                <button
                  onClick={() => onEdit({ type: "agent", data: agent })}
                  className="p-2 text-blue-500 rounded-full hover:text-blue-700 hover:bg-blue-50"
                  title="Edit agent"
                >
                  <PenSquare size={20} />
                </button>
              </>
            )}
            <button
              onClick={() => handleAgentDelete(agent.id)}
              className="px-3 py-1 text-red-500 rounded hover:text-red-700 hover:bg-red-50"
            >
              Delete
            </button>
            <button
              onClick={() => handleAgentActivation(agent, !isActive)}
              className={`px-3 py-1 rounded ${isActive
                ? "text-yellow-500 hover:text-yellow-700 hover:bg-yellow-50"
                : "text-green-500 hover:text-green-700 hover:bg-green-50"
                }`}
            >
              {isActive ? "Deactivate" : "Activate"}
            </button>
          </div>
        </div>
      </div>
    );
  };

  if (isProjectsTab) {
    return null;
  }

  return (
    <FunctionErrorBoundary componentName="Agent Tab">
      <div className="p-6">
        <FunctionErrorBoundary componentName="Agent Form Section">
          <div className="flex justify-end mb-4">
            <select
              className="p-2 border rounded"
              value={formState.agentForm.project}
              onChange={(e) => updateFormState({ project: e.target.value })}
            >
              <option value="">Select Project</option>
              {(projects || []).map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </div>

          <div className="p-6 mb-6 bg-white border rounded">
            <textarea
              placeholder="Instruct a brand-new agent on what it should do"
              value={formState.agentForm.initialPrompt}
              onChange={(e) =>
                updateFormState({ initialPrompt: e.target.value })
              }
              className="w-full h-64 p-2 mb-4 border rounded"
            />

            {/* File Upload Section */}
            <div className="p-4 mb-4 border rounded">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold">
                  Upload Files for Agent
                </h3>
                <div className="flex items-center gap-2">
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    style={{ display: "none" }}
                    onChange={handleFileUpload}
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="px-3 py-1.5 border rounded hover:bg-gray-50 flex items-center gap-1"
                    disabled={uploadingFiles}
                  >
                    <Paperclip size={16} />
                    <span>Select Files</span>
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                {selectedFiles.length === 0 ? (
                  <div className="py-2 text-sm text-center text-gray-500">
                    No files selected yet
                  </div>
                ) : (
                  selectedFiles.map((file) => (
                    <div
                      key={file.name}
                      className="flex items-center justify-between p-2 border rounded"
                    >
                      <div className="flex items-center gap-2">
                        <FileText size={16} className="text-gray-500" />
                        <span className="text-sm">{file.name}</span>
                        <span className="text-xs text-gray-400">
                          ({(file.size / 1024).toFixed(1)}KB)
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRemoveFile(file.name)}
                        className="p-1 text-red-500 rounded-full hover:bg-red-50"
                      >
                        <X size={16} />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
            {/* Multi-Agent Toggle */}
            <div className="flex items-center mb-4">
              <input
                type="checkbox"
                id="createAgentMultiAgentToggle"
                checked={useMultiAgent}
                onChange={(e) => setUseMultiAgent(e.target.checked)}
                className="mr-2"
              />
              <label
                htmlFor="createAgentMultiAgentToggle"
                className="text-sm text-gray-600"
              >
                Use Advanced Multi-Agent System by default
              </label>
            </div>

            <div className="flex justify-end">
              <button
                onClick={handleCreateAgent}
                disabled={isCreating}
                className={`flex items-center gap-2 px-4 py-2 text-white rounded ${isCreating ? "bg-blue-300 cursor-wait" : "bg-blue-500 hover:bg-blue-600"
                  }`}
              >
                {isCreating ? "Creating..." : "Create Agent"}
              </button>
            </div>
          </div>
        </FunctionErrorBoundary>

        <FunctionErrorBoundary componentName="Active Agents List">
          <h2 className="mb-4 text-lg font-bold">Active Agents</h2>
          <div className="mb-8 space-y-4">
            {Array.isArray(activeAgents) && activeAgents.length > 0 ? (
              activeAgents.map((agent) => (
                <FunctionErrorBoundary
                  key={agent.id}
                  componentName={`Agent Card: ${agent.name}`}
                >
                  {renderAgentCard(agent, true)}
                </FunctionErrorBoundary>
              ))
            ) : (
              <div className="py-4 text-center text-gray-500">
                No active agents available
              </div>
            )}
          </div>
        </FunctionErrorBoundary>

        <FunctionErrorBoundary componentName="Deactivated Agents List">
          <h2 className="mb-4 text-lg font-bold">Deactivated Agents</h2>
          <div className="space-y-4">
            {Array.isArray(deactivatedAgents) &&
              deactivatedAgents.length > 0 ? (
              deactivatedAgents.map((agent) => (
                <FunctionErrorBoundary
                  key={agent.id}
                  componentName={`Agent Card: ${agent.name}`}
                >
                  {renderAgentCard(agent, false)}
                </FunctionErrorBoundary>
              ))
            ) : (
              <div className="py-4 text-center text-gray-500">
                No deactivated agents available
              </div>
            )}
          </div>
        </FunctionErrorBoundary>
      </div>
    </FunctionErrorBoundary>
  );
};

export default AgentTab;