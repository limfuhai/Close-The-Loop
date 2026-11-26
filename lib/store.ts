// Add to the top of the file, before any other code
declare global {
  interface Window {
    backendConnection: {
      sendMessage: (message: any) => Promise<any>;
      onMessage: (callback: (data: any) => void) => void;
      connect: () => Promise<any>;
      getStatus: () => Promise<any>;
    };
  }
}

const MAX_HISTORY = 25;

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// Types
export interface ProjectFile {
  id: string;
  name: string;
  path: string;
  size: number;
  type: string;
  uploadedAt: string;
}

export interface ChatMessage {
  id: string;
  content: string;
  sender: string;
  timestamp: string;
  type: 'user' | 'agent' | 'system' | 'llm' | 'orchestrator';
  attachments?: Array<{
    id?: string;
    name: string;
    path: string;
    size: number;
    type: string;
  }>;
  orchestratorContext?: {
    sessionId: string;
    taskId: string;
    requiresMultiLLM: boolean;
  };
}

export interface ErrorState {
  message: string;
  code?: string;
  timestamp: string;
}

export interface FormState {
  agentForm: {
    name: string;
    initialPrompt: string;
    project: string;
  };
}

export interface EditState {
  [id: string]: {
    [type: string]: string;
  };
}

// Update the Agent interface:
export interface Agent {
  id: string;
  name: string;
  initialPrompt: string;
  project: string | null;
  status: 'active' | 'deactivated';
  dateCreated: string;
  lastModified: string;
  preferMultiAgent?: boolean; // Add this line
}

export interface Project {
  id: string;
  name: string;
  description: string;
  agents: string[];
  dateCreated: string;
  lastModified: string;
}

export interface AgentMessage {
  id: string;
  agentId: string;
  content: string;
  timestamp: string;
  sender?: string;
  attachments?: Array<{
    id?: string;
    name: string;
    path: string;
    size: number;
    type: string;
  }>;
  artifacts?: Array<{
    id: string;
    type: 'powerpoint' | 'code' | 'chart' | 'data';
    title: string;
    data: any;
    preview?: string;
  }>;
}
// DEPRECATED, replaced by V4 implementation below
export interface ProjectGroupChat {
  id: string;
  projectId: string;
  messages: ChatMessage[];
  lastActivity: string;
}

export interface V4Agent {
  id: string;
  name: string;
  system_prompt: string;
  status: 'active' | 'idle' | 'terminated';
  group_memberships: string[];
  created_at: string;
  terminated_at?: string;
  metadata?: Record<string, any>;
}

export interface V4GroupChat {
  id: string;
  title: string;
  description?: string;
  created_by: string;
  member_ids: string[];
  created_at: string;
  last_activity: string;
  metadata?: Record<string, any>;
}

export interface V4GroupChatMessage {
  id: string;
  group_chat_id: string;
  sender_id: string;
  sender_name: string;
  content: string;
  created_at: string;
}

export interface AppState {
  // Core State
  projects: Project[];
  activeAgents: Agent[];
  deactivatedAgents: Agent[];
  errors: ErrorState[];
  formState: FormState;
  editStates: EditState;
  projectFiles: Record<string, ProjectFile[]>;

  // Add to AppState interface
  createPlannerTask: (request: string, context?: any) => Promise<any>;
  executeTask: (task: any) => Promise<any>;

  // Chat State (DEPRECATED, replaced by V4 implementation below)
  projectGroupChats: Record<string, ProjectGroupChat>;

  // V4 Group Chat State
  v4GroupChats: Record<string, V4GroupChat>;
  v4GroupChatMessages: Record<string, V4GroupChatMessage[]>;
  v4Agents: V4Agent[];

  // V4 Actions
  addV4GroupChat: (chat: V4GroupChat) => void;
  addV4GroupChatMessage: (groupChatId: string, message: V4GroupChatMessage) => void;
  getV4GroupChatMessages: (groupChatId: string) => V4GroupChatMessage[];
  getV4GroupChatsForProject: (projectId: string) => V4GroupChat[];

  // HTTP API Actions
  sendAgentMessage: (agentId: string, content: string, streaming: boolean, conversationTone?: string, signal?: AbortSignal, description?: string) => Promise<void>;

  // Form State Management
  updateFormState: (form: Partial<FormState['agentForm']>) => void;
  resetFormState: () => void;

  // Error Management
  addError: (error: ErrorState) => void;
  clearErrors: () => void;

  // Agent Management
  addAgent: (agent: Agent) => void;
  deleteAgent: (agentId: string) => void;
  toggleAgentStatus: (agentId: string) => void;
  updateAgent: (agentId: string, updates: Partial<Agent>) => void;
  fetchAgents: () => Promise<void>;

  // Project Management
  setProjects: (projects: Project[]) => void;
  createProject: (projectData: Partial<Project>) => void;
  updateProject: (projectId: string, updates: Partial<Project>) => void;
  deleteProject: (projectId: string) => void;

  // File Management
  getProjectFiles: (projectId: string) => ProjectFile[];
  addProjectFiles: (projectId: string, files: ProjectFile[]) => void;
  removeProjectFile: (projectId: string, fileId: string) => void;
  fetchProjectFiles: (projectId: string) => Promise<ProjectFile[]>;
  uploadProjectFile: (projectId: string, file: File) => Promise<ProjectFile>;
  uploadAgentMessageWithFile: (agentId: string, content: string, file: File, conversationTone?: string, signal?: AbortSignal) => Promise<void>;

  // Edit State Management
  savePersistentEdit: (id: string, type: string, content: string) => void;
  getPersistentEdit: (id: string, type: string) => string | null;
  clearPersistentEdit: (id: string, type: string) => void;

  // Add agent messages state
  agentMessages: Record<string, AgentMessage[]>;

  // Add agent message functions to interface
  addAgentMessage: (agentId: string, message: AgentMessage) => void;
  getAgentMessages: (agentId: string) => AgentMessage[];
  fetchAgentMessages: (agentId: string) => Promise<void>;

  // Project Group Chat Management (DEPRECATED, replaced by V4 implementation below)
  initializeProjectChat: (projectId: string) => void;
  addProjectChatMessage: (projectId: string, message: ChatMessage) => void;
  getProjectChatMessages: (projectId: string) => ChatMessage[];

  //Clerk Token Management
  clerkToken: string | null;
  setClerkToken: (token: string) => void;

  // Multi-Agent System
  startMultiAgentTask: (content: string, agentId?: string, conversationTone?: string, signal?: AbortSignal, description?: string) => Promise<string>;
  getMultiAgentMessages: (agentId: string) => AgentMessage[];

  startMultiAgentTaskWithFiles: (content: string, files?: File[], agentId?: string, conversationTone?: string, signal?: AbortSignal, description?: string) => Promise<string>;
  getAgentProject: (agentId: string) => Project | null;

  orchestratorSessions: Record<string, {
    id: string;
    projectId: string;
    status: string;
    assessment?: any;
    tasks?: any[];
    taskStatus?: Record<string, string>;
    error?: string;
    createdAt: string;
    triggeredBy: string;
  }>;

  triggerOrchestrator: (projectId: string, request: string, agentId: string, signal?: AbortSignal) => Promise<string>;
  reportTaskCompletion: (orchestrationId: string, taskId: string, agentId: string, completedWork: string) => Promise<any>;
  sendOrchestratorMessage: (agentId: string, task: any, orchestrationId: string) => Promise<any>;
  createNewAgent: (initialPrompt: string, additionalData?: any) => Promise<any>;
}

const initialFormState: FormState = {
  agentForm: {
    name: '',
    initialPrompt: '',
    project: '',
  }
};

// Helper function to get the API base URL
const getApiBaseUrl = (): string => {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL;
  if (!apiUrl) {
    throw new Error('NEXT_PUBLIC_API_URL environment variable is not set.');
  }

  return apiUrl;
};

// Helper to detect if running in packaged app
const isPackagedApp = () => {
  return window.electron && window.location.protocol === 'file:';
};


const tonePrefix = {
  neutral: "",
  friendly: "Please respond in a friendly, conversational tone. ",
  professional: "Please respond in a formal and professional tone. ",
  humorous: "Please respond with light humor. ",
  empathetic: "Please respond in an understanding and empathetic tone. ",
}

const useStore = create<AppState>()(
  persist<AppState>(
    (set, get) => ({
      // Initial State
      projects: [],
      activeAgents: [],
      deactivatedAgents: [],
      errors: [],
      formState: initialFormState,
      editStates: {},
      projectFiles: {},
      projectGroupChats: {},
      v4GroupChats: {},
      v4GroupChatMessages: {},
      v4Agents: [],
      clerkToken: null,
      setClerkToken: (token: string) => set({ clerkToken: token }),

      // Add agent messages initial state
      agentMessages: {},

      getAgentProject: (agentId) => {
        const { activeAgents, deactivatedAgents, projects } = get();
        const agent = [...activeAgents, ...deactivatedAgents].find(a => a.id === agentId);
        if (!agent?.project) return null;
        return projects.find(p => p.id === agent.project) || null;
      },
      orchestratorSessions: {},

      triggerOrchestrator: async (projectId, request, agentId, signal) => {
        const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

        try {
          const response = await fetch(`${backendUrl}/api/orchestrator/trigger`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${get().clerkToken || ''}`
            },
            body: JSON.stringify({
              project_id: projectId,
              request: request,
              agent_id: agentId
            }),
            signal
          });

          const result = await response.json();

          if (result.orchestration_id) {
            // Store the orchestration session
            set((state) => ({
              orchestratorSessions: {
                ...state.orchestratorSessions,
                [result.orchestration_id]: {
                  id: result.orchestration_id,
                  projectId: projectId,
                  status: result.status,
                  assessment: result.assessment,
                  tasks: result.tasks,
                  createdAt: new Date().toISOString(),
                  triggeredBy: agentId
                }
              }
            }));

            // Now send tasks to each agent as messages
            if (result.tasks && result.tasks.length > 0) {
              for (const task of result.tasks) {
                const assignedAgentId = task.assigned_agent_id; // This will be the actual agent ID

                // Use the new dedicated orchestrator message function
                await get().sendOrchestratorMessage(assignedAgentId, task, result.orchestration_id);
              }
            }

            return result.orchestration_id;
          }

          throw new Error(result.message || 'Failed to trigger orchestrator');
        } catch (error) {
          console.error('Orchestrator trigger error:', error);
          throw error;
        }
      },

      reportTaskCompletion: async (orchestrationId, taskId, agentId, completedWork) => {
        const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

        try {
          const response = await fetch(`${backendUrl}/api/orchestrator/task-complete`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${get().clerkToken || ''}`
            },
            body: JSON.stringify({
              orchestration_id: orchestrationId,
              task_id: taskId,
              agent_id: agentId,
              completed_work: completedWork
            })
          });

          const result = await response.json();

          // Update task status in store
          const session = get().orchestratorSessions[orchestrationId];
          if (session) {
            set((state) => ({
              orchestratorSessions: {
                ...state.orchestratorSessions,
                [orchestrationId]: {
                  ...session,
                  taskStatus: {
                    ...(session.taskStatus || {}),
                    [taskId]: result.status === 'approved' ? 'completed' : 'needs_revision'
                  }
                }
              }
            }));
          }

          return result;
        } catch (error) {
          console.error('Task completion report error:', error);
          throw error;
        }
      },

      sendOrchestratorMessage: async (agentId: string, task: any, orchestrationId: string) => {
        try {
          // Create orchestrator message with full context
          const messageId = Date.now().toString();
          const timestamp = new Date().toISOString();

          const orchestratorMessage: ChatMessage = {
            id: messageId,
            sender: 'orchestrator',
            content: task.context,
            timestamp: timestamp,
            type: 'orchestrator',
            orchestratorContext: {
              sessionId: orchestrationId,
              taskId: task.task_id,
              requiresMultiLLM: true
            }
          };

          // Add orchestrator message to UI immediately
          get().addAgentMessage(agentId, {
            id: orchestratorMessage.id,
            agentId: agentId,
            content: orchestratorMessage.content,
            timestamp: orchestratorMessage.timestamp,
            sender: orchestratorMessage.sender
          });

          // Create placeholder for response
          const responseId = `response_${Date.now()}`;
          set((state) => ({
            agentMessages: {
              ...state.agentMessages,
              [agentId]: [
                ...(state.agentMessages[agentId] || []),
                {
                  id: responseId,
                  agentId,
                  content: '',
                  timestamp: new Date().toISOString(),
                  sender: 'assistant'
                }
              ]
            }
          }));

          // Packaged app: Use IPC
          if (isPackagedApp()) {
            // Set up message handler for streaming responses
            window.backendConnection.onMessage((data) => {
              if (data.type === 'AGENT_RESPONSE_CHUNK' && data.agentId === agentId) {
                // Update streaming response
                set((state) => {
                  const messages = state.agentMessages[agentId] || [];
                  return {
                    agentMessages: {
                      ...state.agentMessages,
                      [agentId]: messages.map(msg =>
                        msg.id === responseId
                          ? { ...msg, content: msg.content + data.content }
                          : msg
                      )
                    }
                  };
                });
              }
            });

            // Send the orchestrator message through IPC
            await window.backendConnection.sendMessage({
              type: 'ORCHESTRATOR_MESSAGE',
              agentId,
              content: task.context,
              timestamp,
              orchestratorContext: orchestratorMessage.orchestratorContext,
              streaming: true
            });

            return { streaming: true };
          }
          // Development: Use direct HTTP
          else {
            const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';
            // Get project info for context
            const agentProject = get().getAgentProject(agentId);

            // Start streaming connection
            const response = await fetch(`${backendUrl}/api/agent/message/stream`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${get().clerkToken || ''}`
              },
              body: JSON.stringify({
                agentId: agentId,
                projectId: agentProject?.id || null,
                content: task.context,
                timestamp: timestamp,
                sender: 'orchestrator',
                orchestratorContext: orchestratorMessage.orchestratorContext
              })
            });

            if (!response.ok) {
              throw new Error(`Streaming failed: ${response.status}`);
            }

            if (!response.body) {
              throw new Error('Response body is null');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let responseText = '';
            let artifacts: any[] = [];

            try {
              while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');

                for (const line of lines) {
                  if (line.startsWith('data: ')) {
                    try {
                      const data = JSON.parse(line.slice(6));

                      // Handle artifacts
                      if (data.artifacts) {
                        artifacts = data.artifacts;
                      }

                      if (data.complete) {
                        // Task complete - check if we need to report back to orchestrator
                        if (orchestratorMessage.orchestratorContext && responseText) {
                          // Create accomplishment summary
                          const accomplishmentSummary = `
      ## Task Accomplishment Summary
      
      ### What Was Created:
      ${responseText}
      
      ### Artifacts Produced:
      ${artifacts.map(a => `- **${a.title}** (${a.type})`).join('\n')}
      `;

                          // Report completion back to orchestrator
                          await get().reportTaskCompletion(
                            orchestrationId,
                            task.task_id,
                            agentId,
                            accomplishmentSummary
                          );
                        }

                        // Update final message with artifacts if any
                        if (artifacts.length > 0) {
                          set((state) => ({
                            agentMessages: {
                              ...state.agentMessages,
                              [agentId]: state.agentMessages[agentId].map(msg =>
                                msg.id === responseId
                                  ? { ...msg, artifacts: artifacts }
                                  : msg
                              )
                            }
                          }));
                        }

                        return { streaming: true };
                      } else if (data.token) {
                        responseText += data.token;

                        // Update message with current text
                        set((state) => {
                          const messages = state.agentMessages[agentId] || [];
                          return {
                            agentMessages: {
                              ...state.agentMessages,
                              [agentId]: messages.map(msg =>
                                msg.id === responseId
                                  ? { ...msg, content: responseText }
                                  : msg
                              )
                            }
                          };
                        });
                      }
                    } catch (e) {
                      // Skip malformed JSON lines
                    }
                  }
                }
              }
            } catch (error) {
              get().addError({
                message: 'Error in orchestrator streaming response: ' + error.message,
                timestamp: new Date().toISOString()
              });
            } finally {
              reader.releaseLock();
            }

            return { streaming: true };
          }
        } catch (error) {
          console.error('Error sending orchestrator message:', error);
          get().addError({
            message: error instanceof Error ? error.message : 'Failed to send orchestrator message',
            timestamp: new Date().toISOString()
          });
          throw error;
        }
      },

      // In store.ts, modify the sendAgentMessage function
      sendAgentMessage: async (agentId: string, content: string, streaming = true, conversationTone = "neutral", signal?: AbortSignal, description?: string) => {
        try {
          // Create message ID and data
          const messageId = Date.now().toString();
          const timestamp = new Date().toISOString();
          const tonedContent = `${tonePrefix[conversationTone]}: ${content}`

          // Add user message to UI immediately
          get().addAgentMessage(agentId, {
            id: messageId,
            agentId: agentId,
            content:
              content,
            timestamp: timestamp,
            sender: 'user'
          });

          // Packaged app: Use IPC
          if (isPackagedApp()) {
            if (streaming) {
              // Create placeholder for streaming response
              const responseId = `response_${Date.now()}`;
              set((state) => ({
                agentMessages: {
                  ...state.agentMessages,
                  [agentId]: [
                    ...(state.agentMessages[agentId] || []),
                    {
                      id: responseId,
                      agentId,
                      content: '',
                      timestamp: new Date().toISOString(),
                      sender: 'assistant'
                    }
                  ]
                }
              }));

              // Set up message handler for streaming responses
              window.backendConnection.onMessage((data) => {
                if (data.type === 'AGENT_RESPONSE_CHUNK' && data.agentId === agentId) {
                  // Update streaming response
                  set((state) => {
                    const messages = state.agentMessages[agentId] || [];
                    return {
                      agentMessages: {
                        ...state.agentMessages,
                        [agentId]: messages.map(msg =>
                          msg.id === responseId
                            ? { ...msg, content: msg.content + data.content }
                            : msg
                        )
                      }
                    };
                  });
                }
              });

              // Send the message through IPC
              await window.backendConnection.sendMessage({
                type: 'AGENT_MESSAGE',
                agentId,
                content: tonedContent,
                timestamp,
                streaming: true
              });

              return { streaming: true };
            } else {
              // Non-streaming through IPC
              const result = await window.backendConnection.sendMessage({
                type: 'AGENT_MESSAGE',
                agentId,
                content: tonedContent,
                timestamp
              });

              // Add response to UI
              if (result && !result.error) {
                get().addAgentMessage(agentId, {
                  id: Date.now().toString(),
                  agentId: agentId,
                  content: result.content,
                  timestamp: result.timestamp || new Date().toISOString(),
                  sender: 'assistant'
                });
              }

              return result;
            }
          }
          // Development: Use direct HTTP
          else {
            const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

            // FIXED: Added optional chaining and fallback
            const conversationHistory = (get().agentMessages[agentId] || []).filter(({ content }) => !!content).map(({ sender, content }) => ({
              role: sender,
              content
            })).slice(-MAX_HISTORY)

            if (streaming) {
              // Create placeholder for streaming response
              const responseId = `response_${Date.now()}`;
              set((state) => ({
                agentMessages: {
                  ...state.agentMessages,
                  [agentId]: [
                    ...(state.agentMessages[agentId] || []),
                    {
                      id: responseId,
                      agentId,
                      content: '',
                      timestamp: new Date().toISOString(),
                      sender: 'assistant'
                    }
                  ]
                }
              }));


              // Start streaming connection using fetch + POST
              const agentProject = get().getAgentProject(agentId);
              const response = await fetch(`${backendUrl}/api/agent/message/stream`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'Authorization': `Bearer ${get().clerkToken || ''}`
                },
                body: JSON.stringify({
                  agentId: agentId,
                  projectId: agentProject?.id || null,
                  content: tonedContent,
                  timestamp: new Date().toISOString(),
                  conversationHistory: conversationHistory,
                  description: description
                }),
                signal
              });

              if (!response.ok) {
                throw new Error(`Streaming failed: ${response.status}`);
              }

              if (!response.body) {
                throw new Error('Response body is null');
              }
              const reader = response.body.getReader();
              const decoder = new TextDecoder();
              let responseText = '';

              try {
                while (true) {
                  const { done, value } = await reader.read();
                  if (done) break;

                  const chunk = decoder.decode(value, { stream: true });
                  const lines = chunk.split('\n');

                  for (const line of lines) {
                    if (line.startsWith('data: ')) {
                      try {
                        const data = JSON.parse(line.slice(6));

                        // Handle artifacts
                        if (data.artifacts && responseId) {
                          // Store artifacts temporarily - we'll add them when message completes
                          if (!responseText) responseText = '';

                          // Update the message with artifacts when complete
                          set((state) => ({
                            agentMessages: {
                              ...state.agentMessages,
                              [agentId]: state.agentMessages[agentId].map(msg =>
                                msg.id === responseId
                                  ? { ...msg, artifacts: data.artifacts }
                                  : msg
                              )
                            }
                          }));
                        }
                        if (data.complete) {
                          return { streaming: true };
                        } else if (data.token) {
                          responseText += data.token;

                          // Update message with current text
                          set((state) => {
                            const messages = state.agentMessages[agentId] || [];
                            return {
                              agentMessages: {
                                ...state.agentMessages,
                                [agentId]: messages.map(msg =>
                                  msg.id === responseId
                                    ? { ...msg, content: responseText }
                                    : msg
                                )
                              }
                            };
                          });
                        }
                      } catch (e) {
                        // Skip malformed JSON lines
                      }
                    }
                  }
                }
              } catch (error) {
                get().addError({
                  message: 'Error in streaming response: ' + error.message,
                  timestamp: new Date().toISOString()
                });
              } finally {
                reader.releaseLock();
              }

              return { streaming: true };
            } else {
              // Non-streaming API call
              const response = await fetch(`${backendUrl}/api/agent/message`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                  'Authorization': `Bearer ${get().clerkToken || ''}`
                },
                body: JSON.stringify({
                  agentId: agentId,
                  content: tonedContent,
                  timestamp: timestamp,
                  conversationHistory: conversationHistory
                }),
                signal
              });

              // Handle response
              if (!response.ok) {
                throw new Error(`API error: ${response.status}`);
              }

              const responseData = await response.json();

              // Add response to UI
              get().addAgentMessage(agentId, {
                id: Date.now().toString(),
                agentId: agentId,
                content: responseData.content,
                timestamp: responseData.timestamp || new Date().toISOString(),
                sender: 'assistant'
              });

              return responseData;
            }
          }
        } catch (error) {
          console.error('Error sending agent message:', error);
          get().addError({
            message: error instanceof Error ? error.message : 'Failed to send message',
            timestamp: new Date().toISOString()
          });
          throw error;
        }
      },

      // File Upload Method
      uploadProjectFile: async (projectId, file) => {
        try {
          // Packaged app: Use IPC
          if (isPackagedApp()) {
            // FormData can't be directly sent via IPC, so create an object
            const fileObj = {
              name: file.name,
              size: file.size,
              type: file.type,
              projectId: projectId
            };

            // Read file as base64
            const fileReader = new FileReader();
            const fileDataPromise = new Promise((resolve, reject) => {
              fileReader.onload = () => resolve(fileReader.result);
              fileReader.onerror = () => reject(fileReader.error);
              fileReader.readAsDataURL(file);
            });

            const fileData = await fileDataPromise;

            // Send to main process via IPC
            const result = await window.backendConnection.sendMessage({
              type: 'FILE_UPLOAD',
              content: {
                fileData,
                fileName: file.name,
                fileType: file.type,
                fileSize: file.size,
                entityId: projectId,
                entityType: 'project'
              }
            });

            if (result && result.type === 'FILE_UPLOAD_RESULT' && result.content.success) {
              const fileData = result.content.file;
              // Add file to store
              get().addProjectFiles(projectId, [fileData]);
              return fileData;
            } else {
              throw new Error(result?.content?.error || 'File upload failed');
            }
          }
          // Development: Use direct HTTP
          else {
            // Create form data
            const formData = new FormData();
            formData.append('file', file);
            formData.append('entityId', projectId);
            formData.append('entityType', 'project');

            const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

            // Send API request
            const response = await fetch(`${backendUrl}/api/upload`, {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${get().clerkToken || ''}`
              },
              body: formData,
            });

            // Handle response
            if (!response.ok) {
              throw new Error(`Upload failed: ${response.status}`);
            }

            const responseData = await response.json();

            if (!responseData.success) {
              throw new Error(responseData.error || 'Upload failed');
            }

            const fileData = responseData.file;

            // Add file to store
            get().addProjectFiles(projectId, [fileData]);

            return fileData;
          }
        } catch (error) {
          console.error('Error uploading file:', error);
          get().addError({
            message: error instanceof Error ? error.message : 'Failed to upload file',
            timestamp: new Date().toISOString()
          });
          throw error;
        }
      },

      uploadAgentMessageWithFile: async (agentId, content, file, conversationTone = "neutral", signal) => {
        try {
          // Read file as base64 for transmission
          const fileReader = new FileReader();
          const fileDataPromise = new Promise((resolve, reject) => {
            fileReader.onload = () => resolve(fileReader.result);
            fileReader.onerror = () => reject(fileReader.error);
            fileReader.readAsDataURL(file);
          });

          const fileData = await fileDataPromise;
          const tonedContent = `${tonePrefix[conversationTone]}: ${content}`

          // Create attachment object
          const attachment = {
            id: `attachment_${Date.now()}`,
            name: file.name,
            size: file.size,
            type: file.type,
            data: fileData as string, // Base64 data
            path: file.name // File type doesn't have .path, so use .name
          };

          // FIXED: Added safety check for agentMessages
          const conversationHistory = (get().agentMessages[agentId] || []).filter(({ content }) => !!content).map(({ sender, content }) => ({
            role: sender,
            content
          })).slice(-MAX_HISTORY)


          // Add user message to UI
          get().addAgentMessage(agentId, {
            id: Date.now().toString(),
            agentId: agentId,
            content: tonedContent,
            timestamp: new Date().toISOString(),
            sender: 'user',
            attachments: [attachment]
          });

          // Create placeholder for streaming response
          const responseId = `response_${Date.now()}`;
          set((state) => ({
            agentMessages: {
              ...state.agentMessages,
              [agentId]: [
                ...(state.agentMessages[agentId] || []),
                {
                  id: responseId,
                  agentId,
                  content: '',
                  timestamp: new Date().toISOString(),
                  sender: 'assistant'
                }
              ]
            }
          }));

          // Use unified streaming approach with file attachment
          const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

          const response = await fetch(`${backendUrl}/api/agent/message/stream`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${get().clerkToken || ''}`
            },
            body: JSON.stringify({
              agentId: agentId,
              content: content,
              attachments: [attachment],
              timestamp: new Date().toISOString(),
              conversationHistory
            }),
            signal
          });

          if (!response.ok) {
            throw new Error(`Streaming failed: ${response.status}`);
          }

          if (!response.body) {
            throw new Error('Response body is null');
          }
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let responseText = '';

          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;

              const chunk = decoder.decode(value, { stream: true });
              const lines = chunk.split('\n');

              for (const line of lines) {
                if (line.startsWith('data: ')) {
                  try {
                    const data = JSON.parse(line.slice(6));
                    // Inside the streaming loop where you parse data
                    if (data.artifacts) {
                      // Update the message with artifacts
                      set((state) => ({
                        agentMessages: {
                          ...state.agentMessages,
                          [agentId]: state.agentMessages[agentId].map(msg =>
                            msg.id === responseId
                              ? { ...msg, artifacts: data.artifacts }
                              : msg
                          )
                        }
                      }));
                    }
                    if (data.complete) {
                      return;
                    } else if (data.token) {
                      responseText += data.token;

                      // Update streaming response
                      set((state) => {
                        const messages = state.agentMessages[agentId] || [];
                        return {
                          agentMessages: {
                            ...state.agentMessages,
                            [agentId]: messages.map(msg =>
                              msg.id === responseId
                                ? { ...msg, content: responseText }
                                : msg
                            )
                          }
                        };
                      });
                    }
                  } catch (e) {
                    // Skip malformed JSON lines
                  }
                }
              }
            }
          } finally {
            reader.releaseLock();
          }
        } catch (error) {
          console.error('Error sending message with file:', error);
          get().addError({
            message: error instanceof Error ? error.message : 'Failed to send message with file',
            timestamp: new Date().toISOString()
          });
        }
      },

      // Add agent message functions
      addAgentMessage: (agentId, message) => set(state => ({
        agentMessages: {
          ...state.agentMessages,
          [agentId]: [...(state.agentMessages[agentId] || []), message]
        }
      })),

      getAgentMessages: (agentId) => {
        return get().agentMessages[agentId] || [];
      },

      fetchAgentMessages: async (agentId) => {
        try {
          const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

          const response = await fetch(`${backendUrl}/api/messages?agent_id=${agentId}`, {
            method: 'GET',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${get().clerkToken || ''}`
            }
          });

          if (!response.ok) {
            console.error('Failed to fetch agent messages:', response.statusText);
            return;
          }

          const data = await response.json();
          if (data.success && data.messages) {
            // Map DB format to local AgentMessage format
            const formattedMessages = data.messages.map((m: any) => ({
              id: m.id,
              agentId: m.agent_id,
              content: m.content,
              timestamp: m.timestamp || new Date().toISOString(),
              sender: m.role === 'assistant' ? 'assistant' : 'user',
            })).reverse(); // DB sends desc (latest first). UI expects chronological

            set((state) => ({
              agentMessages: {
                ...state.agentMessages,
                [agentId]: formattedMessages
              }
            }));
          }
        } catch (error) {
          console.error('Error fetching agent messages:', error);
        }
      },
      // Add after uploadAgentMessageWithFile or another API function
      createPlannerTask: async (request, context = {}) => {
        try {
          const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

          // Send API request
          const response = await fetch(`${backendUrl}/api/planner/task`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${get().clerkToken || ''}`
            },
            body: JSON.stringify({
              request,
              context
            }),
          });

          if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
          }

          return await response.json();
        } catch (error) {
          console.error('Error creating planner task:', error);
          get().addError({
            message: error instanceof Error ? error.message : 'Failed to create plan',
            timestamp: new Date().toISOString()
          });
          throw error;
        }
      },

      executeTask: async (task) => {
        try {
          const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

          // Send API request
          const response = await fetch(`${backendUrl}/api/executor/task`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${get().clerkToken || ''}`
            },
            body: JSON.stringify(task),
          });

          if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
          }

          return await response.json();
        } catch (error) {
          console.error('Error executing task:', error);
          get().addError({
            message: error instanceof Error ? error.message : 'Failed to execute task',
            timestamp: new Date().toISOString()
          });
          throw error;
        }
      },
      // Form State Management
      updateFormState: (form) => set((state) => ({
        formState: {
          ...state.formState,
          agentForm: {
            ...state.formState.agentForm,
            ...form
          }
        }
      })),

      resetFormState: () => set({ formState: initialFormState }),

      // Error Management
      addError: (error) => set((state) => ({
        errors: [...state.errors, error]
      })),

      clearErrors: () => set({ errors: [] }),

      // Agent Management
      // FIXED: Initialize messages array when adding new agent
      addAgent: (agent) => set((state) => ({
        activeAgents: [...state.activeAgents, agent],
        agentMessages: {
          ...state.agentMessages,
          [agent.id]: []
        }
      })),

      deleteAgent: (agentId) => {
        set((state) => ({
          activeAgents: state.activeAgents.filter(a => a.id !== agentId),
          deactivatedAgents: state.deactivatedAgents.filter(a => a.id !== agentId),
          // Also clean up messages and edit states
          agentMessages: Object.fromEntries(
            Object.entries(state.agentMessages).filter(([id]) => id !== agentId)
          ),
          editStates: Object.fromEntries(
            Object.entries(state.editStates).filter(([id]) => id !== agentId)
          )
        }));
      },

      toggleAgentStatus: (agentId) => set((state) => {
        const activeAgent = state.activeAgents.find(a => a.id === agentId);
        const deactivatedAgent = state.deactivatedAgents.find(a => a.id === agentId);

        if (activeAgent) {
          return {
            activeAgents: state.activeAgents.filter(a => a.id !== agentId),
            deactivatedAgents: [...state.deactivatedAgents, { ...activeAgent, status: 'deactivated' }]
          };
        }

        if (deactivatedAgent) {
          return {
            deactivatedAgents: state.deactivatedAgents.filter(a => a.id !== agentId),
            activeAgents: [...state.activeAgents, { ...deactivatedAgent, status: 'active' }]
          };
        }

        return state;
      }),

      updateAgent: (agentId, updates) => set((state) => ({
        activeAgents: state.activeAgents.map(agent =>
          agent.id === agentId ? { ...agent, ...updates, lastModified: new Date().toISOString() } : agent
        ),
        deactivatedAgents: state.deactivatedAgents.map(agent =>
          agent.id === agentId ? { ...agent, ...updates, lastModified: new Date().toISOString() } : agent
        )
      })),

      fetchAgents: async () => {
        try {
          const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

          const response = await fetch(`${backendUrl}/api/agent/`, {
            method: 'GET',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${get().clerkToken || ''}`
            }
          });

          if (!response.ok) {
            console.error('Failed to fetch agents:', response.statusText);
            return;
          }

          const data = await response.json();
          if (data.success && data.agents) {
            const active = data.agents.filter((a: Agent) => a.status !== 'deactivated');
            const deactivated = data.agents.filter((a: Agent) => a.status === 'deactivated');
            set({ activeAgents: active, deactivatedAgents: deactivated });
          }
        } catch (error) {
          console.error('Error fetching agents:', error);
        }
      },

      // Project Management
      setProjects: (projects) => set({ projects }),

      createProject: (projectData) => set((state) => {
        const newProject: Project = {
          id: Date.now().toString(),
          name: projectData.name || 'New Project',
          description: projectData.description || '',
          agents: [],
          dateCreated: new Date().toISOString(),
          lastModified: new Date().toISOString()
        };
        return { projects: [...state.projects, newProject] };
      }),

      updateProject: (projectId, updates) => set((state) => ({
        projects: state.projects.map(p =>
          p.id === projectId
            ? { ...p, ...updates, lastModified: new Date().toISOString() }
            : p
        )
      })),

      deleteProject: (projectId) => set((state) => ({
        projects: state.projects.filter(p => p.id !== projectId),
        activeAgents: state.activeAgents.map(agent =>
          agent.project === projectId ? { ...agent, project: null } : agent
        ),
        deactivatedAgents: state.deactivatedAgents.map(agent =>
          agent.project === projectId ? { ...agent, project: null } : agent
        )
      })),

      // File Management
      getProjectFiles: (projectId) => {
        return get().projectFiles[projectId] || [];
      },

      addProjectFiles: (projectId, files) => set((state) => ({
        projectFiles: {
          ...state.projectFiles,
          [projectId]: [
            ...(state.projectFiles[projectId] || []),
            ...files
          ]
        }
      })),

      removeProjectFile: (projectId, fileId) => set((state) => ({
        projectFiles: {
          ...state.projectFiles,
          [projectId]: (state.projectFiles[projectId] || []).filter(
            file => file.id !== fileId
          )
        }
      })),

      fetchProjectFiles: async (projectId: string) => {
        try {
          // Packaged app: Use IPC
          if (isPackagedApp()) {
            const result = await window.backendConnection.sendMessage({
              type: 'GET_PROJECT_FILES',
              projectId: projectId
            });

            if (result.success && result.files) {
              // Update store with fetched files
              set(state => ({
                projectFiles: {
                  ...state.projectFiles,
                  [projectId]: result.files
                }
              }));
              return result.files;
            } else {
              throw new Error(result.error || 'Failed to fetch files');
            }
          }
          // Development: Use direct HTTP
          else {
            const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';
            const apiUrl = `${backendUrl}/api/files/project/${projectId}`;

            const response = await fetch(apiUrl);
            const data = await response.json();

            if (data.success && data.files) {
              // Update store with fetched files
              set(state => ({
                projectFiles: {
                  ...state.projectFiles,
                  [projectId]: data.files
                }
              }));
              return data.files;
            } else {
              throw new Error(data.error || 'Failed to fetch files');
            }
          }
        } catch (error) {
          console.error('Error fetching project files:', error);
          get().addError({
            message: 'Failed to fetch project files: ' + (error instanceof Error ? error.message : String(error)),
            timestamp: new Date().toISOString()
          });
          return [];
        }
      },

      // Edit State Management
      savePersistentEdit: (id, type, content) => set((state) => ({
        editStates: {
          ...state.editStates,
          [id]: {
            ...(state.editStates[id] || {}),
            [type]: content
          }
        }
      })),

      getPersistentEdit: (id, type) => {
        const { editStates } = get();
        return editStates[id]?.[type] || null;
      },

      clearPersistentEdit: (id, type) => set((state) => {
        const newStates = { ...state.editStates };
        if (newStates[id]) {
          const { [type]: _, ...remaining } = newStates[id];
          if (Object.keys(remaining).length === 0) {
            delete newStates[id];
          } else {
            newStates[id] = remaining;
          }
        }
        return { editStates: newStates };
      }),

      // Project Group Chat Management // DEPRECATED: Superseded by V4 group chat implementation below
      initializeProjectChat: (projectId) => set((state) => {
        // Only initialize if it doesn't exist already
        if (state.projectGroupChats[projectId]) {
          return state;
        }

        return {
          projectGroupChats: {
            ...state.projectGroupChats,
            [projectId]: {
              id: Date.now().toString(),
              projectId,
              messages: [],
              lastActivity: new Date().toISOString()
            }
          }
        };
      }),
      // DEPRECATED: Superseded by V4 group chat implementation below
      addProjectChatMessage: (projectId, message) => set((state) => ({
        projectGroupChats: {
          ...state.projectGroupChats,
          [projectId]: {
            ...state.projectGroupChats[projectId],
            messages: [
              ...(state.projectGroupChats[projectId]?.messages || []),
              message
            ],
            lastActivity: new Date().toISOString()
          }
        }
      })),
      // DEPRECATED: Superseded by V4 group chat implementation below
      getProjectChatMessages: (projectId) => {
        return get().projectGroupChats[projectId]?.messages || [];
      },

      // V4 Group Chat Actions
      addV4GroupChat: (chat) => set((state) => ({
        v4GroupChats: {
          ...state.v4GroupChats,
          [chat.id]: chat
        }
      })),

      addV4GroupChatMessage: (groupChatId, message) => set((state) => ({
        v4GroupChatMessages: {
          ...state.v4GroupChatMessages,
          [groupChatId]: [
            ...(state.v4GroupChatMessages[groupChatId] || []),
            message
          ]
        }
      })),

      getV4GroupChatMessages: (groupChatId) => {
        return get().v4GroupChatMessages[groupChatId] || [];
      },

      getV4GroupChatsForProject: (projectId) => {
        return Object.values(get().v4GroupChats).filter(
          chat => chat.metadata?.project_id === projectId
        );
      },

      // Multi-Agent System
      startMultiAgentTask: async (content, agentId, conversationTone = "neutral", signal, description) => {
        const tonedContent = `${tonePrefix[conversationTone]}: ${content}`

        try {
          // Add user message immediately if we have an agentId
          if (agentId) {
            get().addAgentMessage(agentId, {
              id: Date.now().toString(),
              agentId: agentId,
              content: content,
              timestamp: new Date().toISOString(),
              sender: 'user'
            });
          }

          // FIXED: Added safety check for agentMessages
          const conversationHistory = agentId ? (get().agentMessages[agentId] || []).filter(({ content }) => !!content).map(({ sender, content }) => ({
            role: sender,
            content
          })).slice(-MAX_HISTORY) : []


          const agentProject = agentId ? get().getAgentProject(agentId) : null;
          const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';
          const response = await fetch(`${backendUrl}/api/agent/multi-llm/stream`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${get().clerkToken || ''}`
            },
            body: JSON.stringify({
              content: tonedContent,
              projectId: agentProject?.id || null,
              attachments: [],
              taskId: `task_${Date.now()}`,
              timestamp: new Date().toISOString(),
              conversationHistory,
              description,
              agentId
            }),
            signal
          });

          if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
          }

          if (!response.body) {
            throw new Error('Response body is null');
          }
          const reader = response.body.getReader();
          const decoder = new TextDecoder();

          const activeMessages = new Map();

          let batch = 0
          let currAgentRole = ""

          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;

              const chunk = decoder.decode(value, { stream: true });
              const lines = chunk.split('\n');

              for (const line of lines) {
                if (line.startsWith('data: ')) {
                  try {
                    const data = JSON.parse(line.slice(6));

                    if (data.complete) {
                      // Clear active message tracking for next batch
                      activeMessages.clear();
                      break;
                    }

                    if (data.agentRole && data.token && agentId) {
                      const agentRole = data.agentRole;
                      if (currAgentRole !== agentRole) {
                        batch++;
                        currAgentRole = agentRole
                      }
                      const timestamp = new Date().toISOString();
                      const messageKey = `${agentRole}_${batch}`
                      set((state) => {
                        const messages = state.agentMessages[agentId] || [];
                        // Check if we have an active message for this agent role
                        let activeMessageId = activeMessages.get(messageKey);
                        let messageIndex = -1;

                        if (activeMessageId) {
                          // Find the message by ID
                          messageIndex = messages.findIndex(msg => msg.id === activeMessageId);
                        }

                        if (messageIndex >= 0) {
                          const updatedMessages = [...messages];
                          updatedMessages[messageIndex] = {
                            ...updatedMessages[messageIndex],
                            content: updatedMessages[messageIndex].content + data.token,
                            timestamp: timestamp,
                            artifacts: data.artifacts || updatedMessages[messageIndex].artifacts
                          };

                          return {
                            agentMessages: {
                              ...state.agentMessages,
                              [agentId]: updatedMessages
                            }
                          };
                        } else {
                          // Create new message for this agent role
                          const newMessageId = `${Date.now()}_${agentRole}_${Math.random()}`;

                          // Store this message ID as active for this agent role
                          activeMessages.set(messageKey, newMessageId);

                          const newMessage = {
                            id: newMessageId,
                            agentId: agentId,
                            content: data.token,
                            timestamp: timestamp,
                            batch,
                            sender: 'assistant',
                            agentRole: agentRole,
                            artifacts: data.artifacts || []
                          };


                          return {
                            agentMessages: {
                              ...state.agentMessages,
                              [agentId]: [...messages, newMessage]
                            }
                          };
                        }
                      });
                    }
                    // Handle artifacts update separately if needed
                    if (data.artifacts && data.agentRole && agentId) {
                      set((state) => {
                        const messages = state.agentMessages[agentId] || [];
                        const activeMessageId = activeMessages.get(data.agentRole);

                        if (activeMessageId) {
                          const messageIndex = messages.findIndex(msg => msg.id === activeMessageId);

                          if (messageIndex >= 0) {
                            const updatedMessages = [...messages];
                            updatedMessages[messageIndex] = {
                              ...updatedMessages[messageIndex],
                              artifacts: data.artifacts
                            };

                            return {
                              agentMessages: {
                                ...state.agentMessages,
                                [agentId]: updatedMessages
                              }
                            };
                          }
                        }
                        return state;
                      });
                    }
                  } catch (e) {
                    // Skip malformed JSON lines
                    console.warn('Malformed JSON in stream:', e);
                  }
                }
              }
            }
          } catch (error) {
            get().addError({
              message: 'Error in multi-agent streaming: ' + error.message,
              timestamp: new Date().toISOString()
            });
          } finally {
            reader.releaseLock();
          }

          return agentId || 'completed';
        } catch (error) {
          console.error('Error starting multi-agent task:', error);
          get().addError({
            message: error instanceof Error ? error.message : 'Failed to start multi-agent task',
            timestamp: new Date().toISOString()
          });
          throw error;
        }
      },

      startMultiAgentTaskWithFiles: async (content, files = [], agentId, conversationTone = "neutral", signal, description) => {
        try {
          const tonedContent = `${tonePrefix[conversationTone]}: ${content}`
          // Process files into attachments
          const attachments: Array<{ name: string; size: number; type: string; data: string }> = [];
          for (const file of files) {
            const fileReader = new FileReader();
            const fileDataPromise = new Promise<string>((resolve, reject) => {
              fileReader.onload = () => resolve(fileReader.result as string);
              fileReader.onerror = () => reject(fileReader.error);
              fileReader.readAsDataURL(file);
            });

            const fileData = await fileDataPromise;
            attachments.push({
              name: file.name,
              size: file.size,
              type: file.type,
              data: fileData
            });
          }

          // FIXED: Added safety check for agentMessages
          const conversationHistory = agentId ? (get().agentMessages[agentId] || []).filter(({ content }) => !!content).map(({ sender, content }) => ({
            role: sender,
            content
          })).slice(-MAX_HISTORY) : []

          // Add user message immediately if we have an agentId
          if (agentId) {
            get().addAgentMessage(agentId, {
              id: Date.now().toString(),
              agentId: agentId,
              content: content,
              timestamp: new Date().toISOString(),
              sender: 'user',
              attachments: attachments.map(att => ({
                id: att.name,
                name: att.name,
                path: att.name,
                size: att.size,
                type: att.type
              }))
            });
          }

          // Start streaming multi-agent task with files
          const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

          const response = await fetch(`${backendUrl}/api/agent/multi-llm/stream`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${get().clerkToken || ''}`
            },
            body: JSON.stringify({
              content: tonedContent,
              attachments: attachments,
              taskId: `task_${Date.now()}`,
              timestamp: new Date().toISOString(),
              conversationHistory,
              description,
              agentId
            }),
            signal
          });

          if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
          }

          if (!response.body) {
            throw new Error('Response body is null');
          }
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          const activeMessages = new Map();

          let batch = 0
          let currAgentRole = ""

          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;

              const chunk = decoder.decode(value, { stream: true });
              const lines = chunk.split('\n');

              for (const line of lines) {
                if (line.startsWith('data: ')) {
                  try {
                    const data = JSON.parse(line.slice(6));

                    // Handle artifacts by agent role
                    if (data.complete) {
                      // Clear active message tracking for next batch
                      activeMessages.clear();
                      break;
                    }

                    if (data.agentRole && data.token && agentId) {
                      const agentRole = data.agentRole;
                      if (currAgentRole !== agentRole) {
                        batch++;
                        currAgentRole = agentRole
                      }
                      const timestamp = new Date().toISOString();
                      const messageKey = `${agentRole}_${batch}`
                      // Update the current message with artifacts
                      set((state) => {
                        const messages = state.agentMessages[agentId] || [];
                        // Check if we have an active message for this agent role
                        let activeMessageId = activeMessages.get(messageKey);
                        let messageIndex = -1;

                        if (activeMessageId) {
                          // Find the message by ID
                          messageIndex = messages.findIndex(msg => msg.id === activeMessageId);
                        }

                        if (messageIndex >= 0) {
                          // Update existing message - append token
                          const updatedMessages = [...messages];
                          updatedMessages[messageIndex] = {
                            ...updatedMessages[messageIndex],
                            content: updatedMessages[messageIndex].content + data.token,
                            timestamp: timestamp,
                            artifacts: data.artifacts || updatedMessages[messageIndex].artifacts
                          };

                          return {
                            agentMessages: {
                              ...state.agentMessages,
                              [agentId]: updatedMessages
                            }
                          };
                        } else {
                          // Create new message for this agent role
                          const newMessageId = `${Date.now()}_${agentRole}_${Math.random()}`;

                          // Store this message ID as active for this agent role
                          activeMessages.set(messageKey, newMessageId);

                          const newMessage = {
                            id: newMessageId,
                            agentId: agentId,
                            content: data.token,
                            timestamp: timestamp,
                            batch,
                            sender: 'assistant',
                            agentRole: agentRole,
                            artifacts: data.artifacts || []
                          };
                          return {
                            agentMessages: {
                              ...state.agentMessages,
                              [agentId]: [...messages, newMessage]
                            }
                          };
                        }
                      });
                    }
                    // Handle artifacts update separately if needed
                    if (data.artifacts && data.agentRole && agentId) {
                      set((state) => {
                        const messages = state.agentMessages[agentId] || [];
                        const activeMessageId = activeMessages.get(data.agentRole);

                        if (activeMessageId) {
                          const messageIndex = messages.findIndex(msg => msg.id === activeMessageId);

                          if (messageIndex >= 0) {
                            const updatedMessages = [...messages];
                            updatedMessages[messageIndex] = {
                              ...updatedMessages[messageIndex],
                              artifacts: data.artifacts
                            };

                            return {
                              agentMessages: {
                                ...state.agentMessages,
                                [agentId]: updatedMessages
                              }
                            };
                          }
                        }

                        return state;
                      });
                    }
                  } catch (e) {
                    // Skip malformed JSON lines
                    console.warn('Malformed JSON in stream:', e);
                  }
                }
              }
            }
          } catch (error) {
            get().addError({
              message: 'Error in multi-agent streaming: ' + error.message,
              timestamp: new Date().toISOString()
            });
          } finally {
            reader.releaseLock();
          }

          return agentId || 'completed';
        } catch (error) {
          console.error('Error starting multi-agent task with files:', error);
          get().addError({
            message: error instanceof Error ? error.message : 'Failed to start multi-agent task with files',
            timestamp: new Date().toISOString()
          });
          throw error;
        }
      },

      getMultiAgentMessages: (agentId) => {
        // Just return the agent's messages - no need for separate multi-agent storage
        return get().agentMessages[agentId] || [];
      },

      createNewAgent: async (initialPrompt: string, additionalData?: any): Promise<any> => {
        try {
          const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8770';

          const requestBody = {
            initialPrompt,
            ...(additionalData || {})
          };

          const response = await fetch(`${backendUrl}/api/agent/`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${get().clerkToken || ''}`
            },
            body: JSON.stringify(requestBody)
          });

          if (!response.ok) {
            console.error('Failed to create agent:', response.statusText);
            return { name: 'New Agent' };
          }

          const data = await response.json();
          return data;
        } catch (error) {
          console.error('Error creating agent:', error);
          return { name: 'New Agent' };
        }
      }
    }),

    {
      name: 'opexassistant-store',
      storage: {
        getItem: (name) => {
          const str = localStorage.getItem(name);
          return str ? JSON.parse(str) : null;
        },
        setItem: (name, value) => {
          localStorage.setItem(name, JSON.stringify(value));
        },
        removeItem: (name) => {
          localStorage.removeItem(name);
        },
      },
      partialize: (state) => {
        // Create an object with just the properties we want to persist
        const persistedData = {
          projects: state.projects,
          activeAgents: state.activeAgents,
          deactivatedAgents: state.deactivatedAgents,
          projectFiles: state.projectFiles,
          projectGroupChats: state.projectGroupChats,
          agentMessages: state.agentMessages,
          v4GroupChats: state.v4GroupChats,
          v4GroupChatMessages: state.v4GroupChatMessages,
          v4Agents: state.v4Agents,
        };

        // Cast it to "any" to bypass TypeScript's type checking
        // This is safe because the persist middleware will handle it correctly
        return persistedData as any;
      }
    }
  )
);

export default useStore;

/**
 * Generate an agent name based on the initial prompt
 * Makes a synchronous POST request to /api/agent/generate-name
 */