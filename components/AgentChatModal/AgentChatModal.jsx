import { FunctionErrorBoundary } from "@/components/ErrorBoundaries";
import {
  Brain,
  Cog,
  FileCheck,
  FileText,
  Loader2,
  MessageSquare,
  MessageCircle,
  Paperclip,
  Send,
  StopCircle,
  Users,
  X,
} from "lucide-react";
import ArtifactViewer from "../ArtifactViewer";
import Markdown from "./components/Markdown";
import { useAgentChatModal } from "./useAgentChatModal";

const getAgentRoleBadge = (sender, batch) => {
  const roleConfig = {
    planner: {
      icon: Brain,
      color: "bg-purple-100 text-purple-700 border-purple-300",
      label: `Planner - ${batch}`,
    },
    executor: {
      icon: Cog,
      color: "bg-blue-100 text-blue-700 border-blue-300",
      label: `Executor - ${batch}`,
    },
    summarizer: {
      icon: FileCheck,
      color: "bg-green-100 text-green-700 border-green-300",
      label: `Summarizer - ${batch}`,
    },
    group_chat_context: {
      icon: MessageCircle,
      color: "bg-yellow-100 text-yellow-700 border-yellow-300",
      label: `Group Chat Update - ${batch}`,
    },
    agent_spawned: {
      icon: Users,
      color: "bg-emerald-100 text-emerald-700 border-emerald-300",
      label: `Agent Spawned - ${batch}`,
    },
  };

  const config = roleConfig[sender.toLowerCase()];
  if (!config) return null;

  const Icon = config.icon;
  return (
    <div
      className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium border ${config.color} mb-2`}
    >
      <Icon size={14} />
      {config.label}
    </div>
  );
};

const AgentChatModal = ({ agent, onClose, messages }) => {
  const {
    fileInputRef,
    chatEndRef,
    chatInputRef,
    newMessage,
    selectedArtifact,
    setSelectedArtifact,
    conversationTone,
    setConversationTone,
    orchestratorTask,
    selectedFiles,
    isSending,
    isUseMultiAgent,
    isChatInputDisabled,
    setIsUseMultiAgent,
    handleFileSelect,
    handleRemoveFile,
    handleMessageChange,
    handleOnKeydown,
    handleSendMessage,
    handleAbortChat,
  } = useAgentChatModal({
    agent,
    messages,
  });

  return (
    <FunctionErrorBoundary componentName={`Agent Chat Modal: ${agent.name}`}>
      <div
        className={`fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 ${
          selectedArtifact ? "artifact-open" : ""
        }`}
      >
        <div
          className={`bg-white rounded-lg w-full h-full flex ${
            selectedArtifact ? "flex-row" : "flex-col"
          }`}
        >
          <div
            className={`${
              selectedArtifact ? "w-1/2" : "w-full"
            } h-full flex flex-col`}
          >
            {/* Header with agent info */}
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <div className="flex items-center gap-2">
                <MessageSquare className="w-6 h-6 text-blue-500" />
                <h2 className="text-xl font-bold">{agent.name}</h2>
              </div>
              <button
                onClick={onClose}
                className="p-2 text-gray-500 rounded-full hover:text-gray-700 hover:bg-gray-100"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            {/* Message content area - centered with max width */}
            <div className="flex justify-center flex-grow p-6 overflow-auto">
              <div className="relative w-full max-w-3xl">
                <FunctionErrorBoundary componentName="Message List">
                  <div className="mb-6 space-y-4">
                    {messages.length === 0 ? (
                      <div className="py-8 text-center text-gray-500">
                        No messages yet. Start a conversation!
                      </div>
                    ) : (
                      messages.map((msg, idx) => (
                        <FunctionErrorBoundary
                          key={msg.id}
                          componentName={`Message: ${msg.id}`}
                        >
                          <div
                            className={`mb-4 ${
                              msg.sender !== "user" ? "" : "flex justify-end"
                            }`}
                          >
                            <div
                              className={`p-4 rounded-lg shadow-sm max-w-[80%] ${
                                msg.sender !== "user"
                                  ? "bg-blue-50"
                                  : "bg-white border"
                              }`}
                            >
                              {["planner", "executor", "summarizer", "group_chat_context", "agent_spawned"].includes(
                                msg.agentRole?.toLowerCase()
                              ) && getAgentRoleBadge(msg.agentRole, msg.batch)}
                              {!msg.content &&
                                !messages.length - 1 &&
                                !isSending && (
                                  <div className="font-mono text-sm text-gray-400">
                                    Empty
                                  </div>
                                )}

                              {!msg.content &&
                                isSending &&
                                idx === messages.length - 1 && (
                                  <div className="flex items-center gap-1 animate-pulse">
                                    <Loader2
                                      className="animate-spin"
                                      size={16}
                                    />
                                    Thinking
                                  </div>
                                )}
                              <div className="message-content">
                                <Markdown
                                  text={msg.content}
                                  artifacts={msg.artifacts}
                                  setSelectedArtifact={setSelectedArtifact}
                                />
                              </div>
                              {msg.attachments &&
                                msg.attachments.length > 0 && (
                                  <div className="pt-2 mt-2 border-t border-gray-200">
                                    <div className="mb-1 text-xs font-medium text-gray-500">
                                      Attachments:
                                    </div>
                                    <div className="flex flex-wrap gap-2">
                                      {msg.attachments.map((file, index) => (
                                        <div
                                          key={file.id || `file-${index}`}
                                          className="inline-flex items-center gap-1 px-2 py-1 text-sm bg-gray-100 rounded"
                                        >
                                          <FileText
                                            size={14}
                                            className="text-blue-500"
                                          />
                                          <span>{file.name}</span>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}

                              {msg.artifacts && msg.artifacts.length > 0 && (
                                <div className="mt-3 space-y-2">
                                  {msg.artifacts.map((artifact) => (
                                    <div
                                      key={artifact.id}
                                      className="flex items-center gap-3 p-3 rounded-lg cursor-pointer artifact-card bg-gray-50 hover:bg-gray-100"
                                      onClick={() =>
                                        setSelectedArtifact(artifact)
                                      }
                                    >
                                      <FileText
                                        size={24}
                                        className="text-blue-500"
                                      />
                                      <div className="flex-1">
                                        <h4 className="font-semibold">
                                          {artifact.title}
                                        </h4>
                                        <p className="text-sm text-gray-600">
                                          Click to view presentation
                                        </p>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              )}

                              <div className="mt-1 text-xs text-gray-400">
                                {new Date(msg.timestamp).toLocaleTimeString()}
                              </div>
                            </div>
                          </div>
                        </FunctionErrorBoundary>
                      ))
                    )}
                    <div ref={chatEndRef} />
                  </div>
                </FunctionErrorBoundary>

                <FunctionErrorBoundary componentName="Message Input">
                  <div className="sticky w-full max-w-3xl p-4 bg-white border rounded-lg -bottom-4">
                    {/* ADD THE VISUAL INDICATOR HERE */}
                    {orchestratorTask && (
                      <div className="p-2 mb-3 bg-blue-100 border border-blue-300 rounded">
                        <span className="flex items-center gap-2 text-sm">
                          <span>🎼</span>
                          <span>
                            Processing orchestrator task:{" "}
                            {orchestratorTask.taskId}
                          </span>
                        </span>
                      </div>
                    )}

                    {/* File input (hidden) */}
                    <input
                      type="file"
                      ref={fileInputRef}
                      onChange={handleFileSelect}
                      style={{ display: "none" }}
                      multiple
                    />

                    {/* Selected file preview */}
                    {selectedFiles.length > 0 && (
                      <div className="mb-2 space-y-2">
                        {selectedFiles.map((file) => (
                          <div
                            key={file.name}
                            className="flex items-center justify-between p-2 border rounded bg-gray-50"
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
                              title="Remove file"
                            >
                              <X size={16} />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <label
                            htmlFor="tone"
                            className="text-sm text-gray-600"
                          >
                            Conversation Tone
                          </label>
                          <select
                            id="tone"
                            value={conversationTone}
                            onChange={(e) =>
                              setConversationTone(e.target.value)
                            }
                            className="px-2 py-1 text-sm border rounded"
                            disabled={isSending}
                          >
                            <option value="neutral">Neutral</option>
                            <option value="friendly">Friendly</option>
                            <option value="professional">Professional</option>
                            <option value="humorous">Humorous</option>
                            <option value="empathetic">Empathetic</option>
                          </select>
                        </div>
                      </div>

                      <textarea
                        className="w-full p-3 border rounded-lg resize-none"
                        placeholder="Type your message..."
                        rows="3"
                        value={newMessage}
                        onChange={handleMessageChange}
                        onKeyDown={handleOnKeydown}
                        ref={chatInputRef}
                        disabled={isSending}
                      />

                      <div className="flex items-center justify-between">
                        <div className="flex items-center">
                          {/* File attachment button */}
                          <button
                            onClick={() => fileInputRef.current?.click()}
                            className="p-2 text-gray-500 rounded hover:text-blue-500"
                            title="Attach file"
                            disabled={isSending}
                          >
                            <Paperclip size={20} />
                          </button>

                          {/* Multi-agent toggle */}
                          <div className="flex items-center ml-2">
                            <input
                              type="checkbox"
                              id="multiAgentToggle"
                              checked={isUseMultiAgent}
                              onChange={() =>
                                setIsUseMultiAgent((prev) => !prev)
                              }
                              className="mr-2"
                            />
                            <label
                              htmlFor="multiAgentToggle"
                              className="text-sm text-gray-600"
                            >
                              Use Advanced Multi-Agent System
                            </label>
                          </div>
                        </div>

                        {/* Send button - this needs to be inside the flex container */}
                        <button
                          onClick={() =>
                            isSending ? handleAbortChat() : handleSendMessage()
                          }
                          disabled={!isSending && isChatInputDisabled}
                          className={`px-4 py-2 rounded flex items-center gap-2 ${
                            isSending
                              ? "bg-red-500 text-white hover:bg-red-600"
                              : isChatInputDisabled
                                ? "bg-gray-100 text-gray-400 cursor-not-allowed"
                                : "bg-blue-500 text-white hover:bg-blue-600"
                          }`}
                        >
                          {isSending ? (
                            <>
                              <StopCircle size={16} className="animate-pulse" />
                              <span>Stop...</span>
                            </>
                          ) : (
                            <>
                              <Send size={16} />
                              <span>Send</span>
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  </div>
                </FunctionErrorBoundary>
              </div>
            </div>
          </div>

          {selectedArtifact && (
            <div className="w-1/2 h-full border-l">
              <ArtifactViewer
                artifact={selectedArtifact}
                onClose={() => setSelectedArtifact(null)}
              />
            </div>
          )}
        </div>
      </div>
    </FunctionErrorBoundary>
  );
};

export default AgentChatModal;
