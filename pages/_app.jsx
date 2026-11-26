// react/pages/_app.jsx
import AgentChatModal from "@/components/AgentChatModal/AgentChatModal";
import { DiagnosticErrorBoundary } from "@/components/ErrorBoundaries";
import {
  ClerkProvider,
  RedirectToSignIn,
  SignedIn,
  SignedOut,
  useAuth,
  UserButton,
} from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { DndProvider } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";
import EditAgentModal from "../components/EditAgentModal";
import EmailAccountsModal from "../components/EmailAccountsModal";
import useStore from "../lib/store";
import CustomAgentsPage from "../pages/custom";
import ProjectsPage from "../pages/projects";
import "../styles/globals.css";
// Local mode: no Clerk key means no login. The backend ignores the token.
const LOCAL_MODE = !process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
const LOCAL_AUTH = { getToken: async () => "local", isSignedIn: true };

// AppContent component - contains all app logic and can safely use useAuth
function AppContent() {
  const [activeTab, setActiveTab] = useState("custom");
  const [editing, setEditing] = useState(null);
  const [chatting, setChatting] = useState(null);

  const isProjectsTab = activeTab === "projects";
  const {
    projects,
    activeAgents,
    deactivatedAgents,
    setProjects,
    addAgent,
    updateAgent,
    deleteAgent,
    toggleAgentStatus,
    formState,
    agentMessages,
    addAgentMessage,
    getAgentMessages,
    fetchAgentMessages,
  } = useStore();

  useEffect(() => {
    const allAgents = [...activeAgents, ...deactivatedAgents];

    if (
      editing?.type === "agent" &&
      !allAgents.find((agent) => agent.id === editing.data.id)
    ) {
      setEditing(null);
    }

    if (chatting && !allAgents.find((agent) => agent.id === chatting.id)) {
      setChatting(null);
    }

    if (
      editing?.type === "project" &&
      !projects.find((project) => project.id === editing.data.id)
    ) {
      setEditing(null);
    }
  }, [activeAgents, deactivatedAgents, projects, editing, chatting]);

  const [connectionAttemptComplete, setConnectionAttemptComplete] =
    useState(false);

  // Add dynamic styles for artifact viewer
  useEffect(() => {
    const style = document.createElement("style");
    style.textContent = `
      /* Artifact cards in messages */
      .artifact-card {
        transition: all 0.2s ease;
        border: 1px solid #e5e7eb;
      }
      
      .artifact-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
      }
      
      /* Split view for artifacts */
      .artifact-open .chat-section {
        transition: width 0.3s ease;
      }
      
      /* PowerPoint viewer styles */
      .powerpoint-viewer {
        height: 100%;
        display: flex;
        flex-direction: column;
        background: #f9fafb;
      }
      
      .slide-container {
        flex: 1;
        background: white;
        margin: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 40px;
        overflow: auto;
      }
      
      .slide {
        width: 100%;
        max-width: 800px;
        text-align: center;
      }
      
      .slide h2 {
        font-size: 2rem;
        font-weight: bold;
        margin-bottom: 2rem;
        color: #1f2937;
      }
      
      .slide-content {
        text-align: left;
        line-height: 1.6;
      }
      
      .slide-content p {
        margin-bottom: 1rem;
      }
      
      .slide-content img {
        max-width: 100%;
        height: auto;
        margin: 1rem 0;
        border-radius: 4px;
      }
      
      .slide-controls {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 2rem;
        padding: 1rem;
        background: white;
        border-top: 1px solid #e5e7eb;
      }
      
      .slide-controls button {
        padding: 0.5rem 1rem;
        border: 1px solid #d1d5db;
        border-radius: 4px;
        background: white;
        cursor: pointer;
        transition: all 0.2s;
      }
      
      .slide-controls button:hover:not(:disabled) {
        background: #f3f4f6;
        border-color: #9ca3af;
      }
      
      .slide-controls button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      
      .slide-thumbnails {
        display: flex;
        gap: 10px;
        padding: 20px;
        background: white;
        overflow-x: auto;
        border-top: 1px solid #e5e7eb;
      }
      
      .thumbnail {
        min-width: 120px;
        height: 80px;
        border: 2px solid transparent;
        cursor: pointer;
        background: #f0f0f0;
        border-radius: 4px;
        padding: 10px;
        transition: all 0.2s;
      }
      
      .thumbnail:hover {
        border-color: #60a5fa;
        background: #e0f2fe;
      }
      
      .thumbnail.active {
        border-color: #2563eb;
        background: #dbeafe;
      }
      
      .thumbnail-content h4 {
        font-size: 0.75rem;
        font-weight: 600;
        color: #374151;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      
      /* Artifact viewer header */
      .artifact-viewer {
        height: 100%;
        display: flex;
        flex-direction: column;
        background: #f9fafb;
      }
      
      .artifact-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 1.5rem;
        background: white;
        border-bottom: 1px solid #e5e7eb;
      }
      
      .artifact-header h3 {
        font-size: 1.125rem;
        font-weight: 600;
        color: #111827;
      }
      
      .artifact-tabs {
        display: flex;
        background: white;
        border-bottom: 1px solid #e5e7eb;
      }
      
      .artifact-tabs button {
        padding: 0.75rem 1.5rem;
        border: none;
        background: none;
        cursor: pointer;
        font-weight: 500;
        color: #6b7280;
        border-bottom: 2px solid transparent;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        gap: 0.5rem;
      }
      
      .artifact-tabs button:hover {
        color: #374151;
      }
      
      .artifact-tabs button.active {
        color: #2563eb;
        border-bottom-color: #2563eb;
      }
      
      .artifact-content {
        flex: 1;
        overflow: auto;
      }
      
      .artifact-actions {
        padding: 1rem;
        background: white;
        border-top: 1px solid #e5e7eb;
        display: flex;
        justify-content: center;
      }
      
      .artifact-actions button {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 1rem;
        background: #2563eb;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-weight: 500;
        transition: all 0.2s;
      }
      
      .artifact-actions button:hover {
        background: #1d4ed8;
      }
    `;
    document.head.appendChild(style);

    return () => {
      document.head.removeChild(style);
    };
  }, []);

  // Better implementation
  useEffect(() => {
    const checkConnection = async () => {
      try {
        console.log(
          "Application initialized, using backend at:",
          process.env.NEXT_PUBLIC_API_URL || "environment variable not set"
        );
        setConnectionAttemptComplete(true);
      } catch (error) {
        console.error("Error during connection check:", error);
        setConnectionAttemptComplete(true);
      }
    };

    // CALL THE FUNCTION - this was missing!
    checkConnection();

    // Add a safety timeout to ensure the UI shows even if all checks fail
    const timeout = setTimeout(() => {
      if (!connectionAttemptComplete) {
        console.log("Connection check timed out, showing UI anyway");
        setConnectionAttemptComplete(true);
      }
    }, 3000);

    return () => clearTimeout(timeout);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // eslint-disable-next-line react-hooks/rules-of-hooks
  const { getToken, isSignedIn } = LOCAL_MODE ? LOCAL_AUTH : useAuth();
  const setClerkToken = useStore((state) => state.setClerkToken);
  const fetchAgents = useStore((state) => state.fetchAgents);

  useEffect(() => {
    const refreshToken = async () => {
      if (!isSignedIn) return;
      try {
        const token = await getToken();
        if (token) {
          setClerkToken(token);
          fetchAgents();
        }
      } catch (error) {
        console.log("Could not refresh Clerk token:", error);
      }
    };
    if (connectionAttemptComplete) {
      refreshToken();
    }
  }, [connectionAttemptComplete, isSignedIn, getToken, setClerkToken, fetchAgents]);

  // Bridge connection state
  const [bridgeConnected, setBridgeConnected] = useState(false);
  const [showBridgeInfo, setShowBridgeInfo] = useState(false);
    
  // Selected email accounts
  const [showEmailAccounts, setShowEmailAccounts] = useState(false);

  // Manage Stripe subscription portal
  const handleManageSubscription = async () => {
    try {
      const token = await getToken();
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8770";
      const response = await fetch(`${apiUrl}/api/billing/portal`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
        },
      });
      const data = await response.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        alert(data.error || "No active subscription found. Please subscribe first.");
      }
    } catch (error) {
      console.error("Billing portal error:", error);
      alert("Unable to open billing portal. Please try again later.");
    }
  };

  // Download bridge file with embedded API key
  const handleDownloadBridge = async () => {
    try {
      const token = await getToken();
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8770";

      const response = await fetch(`${apiUrl}/api/bridge/download`, {
        method: "GET",
        headers: {
          "Authorization": `Bearer ${token}`,
        },
      });

      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'bridge.py';
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        // Show instructions
        setShowBridgeInfo(true);
      } else {
        const error = await response.json();
        alert(error.error || "Failed to download bridge");
      }
    } catch (error) {
      console.error("Bridge download error:", error);
      alert("Error downloading bridge file");
    }
  };

  // Loading check
  if (!connectionAttemptComplete) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-b from-sky-100 via-blue-100 to-cyan-100">
        <div className="text-center">
          <div className="w-10 h-10 mx-auto border-b-2 border-blue-500 rounded-full animate-spin"></div>
          <p className="mt-2">Initializing...</p>
        </div>
      </div>
    );
  }

  const renderComponents = () => {
    // Determine if we're on the projects tab for contextProps
    const isProjectsTab = activeTab === "projects";

    // Create context object with proper isProjectsTab value
    const contextProps = {
      projects,
      onCreateAgent: handleCreateAgent,
      onEdit: handleEdit,
      onChat: handleChat,
      activeAgents,
      deactivatedAgents,
      setProjects,
      formState,
      isProjectsTab,
    };

    return (
      <div className="tab-content">
        <div style={{ display: activeTab === "custom" ? "block" : "none" }}>
          <CustomAgentsPage {...contextProps} />
        </div>
        <div style={{ display: activeTab === "projects" ? "block" : "none" }}>
          <ProjectsPage {...contextProps} />
        </div>
      </div>
    );
  };

  const handleEdit = (editData) => {
    if (
      (editData.type === "agent" && !isProjectsTab) ||
      (editData.type === "project" && isProjectsTab)
    ) {
      setEditing(editData);
    }
  };

  const handleChat = (agent) => {
    if (!isProjectsTab) {
      fetchAgentMessages(agent.id);
      setChatting(agent);
    }
  };

  const handleTabChange = (tabId) => {
    setEditing(null);
    setChatting(null);
    setActiveTab(tabId);
  };

  const handleCreateAgent = (newAgent) => {
    addAgent(newAgent);

    // Open the chat modal for the new agent
    setTimeout(() => {
      setChatting(newAgent);
    }, 100);
  };

  const handleSaveEdit = (editedData) => {
    if (editedData.type === "project") {
      setProjects((prev) =>
        prev.map((p) => (p.id === editedData.id ? editedData : p))
      );
    } else {
      updateAgent(editedData.id, editedData);
    }
    setEditing(null);
  };

  // Create context object to pass to Component
  const contextProps = {
    projects,
    onCreateAgent: handleCreateAgent,
    onEdit: handleEdit,
    onChat: handleChat,
    activeAgents,
    deactivatedAgents,
    setProjects,
    formState,
    isProjectsTab,
  };

  return (
    <DiagnosticErrorBoundary componentName="Root Layout">
      <DndProvider backend={HTML5Backend}>
        <div className="min-h-screen bg-gradient-to-b from-sky-100 via-blue-100 to-cyan-100">
          <div className="w-full p-6 mx-auto">
            <div className="flex items-center justify-between mb-6">
              <h1 className="text-2xl font-bold">Boundary</h1>
              <div className="flex items-center gap-3">
                {/* Big Red Bridge Download Button */}
                <button
                  onClick={handleDownloadBridge}
                  className="px-6 py-3 bg-red-600 hover:bg-red-700 text-white font-bold rounded-lg shadow-lg transition-all duration-200 transform hover:scale-105"
                >
                  🌊 Download Bridge
                </button>
                  {!LOCAL_MODE && (
                  <>
                    <button
                      onClick={() => setShowEmailAccounts(true)}
                      className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg transition-all duration-200"
                    >
                      📮 Email Accounts
                    </button>
                    <button
                      onClick={handleManageSubscription}
                      className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-lg transition-all duration-200"
                    >
                      Manage Subscription
                    </button>
                    <UserButton afterSignOutUrl="/" />
                  </>
                )}
              </div>
            </div>

            {/* Bridge Setup Instructions Modal */}
            {showBridgeInfo && (
              <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                <div className="bg-white rounded-lg p-8 max-w-2xl mx-4">
                  <h2 className="text-2xl font-bold mb-4">🎉 Bridge downloaded!</h2>
                  <div className="space-y-4 text-left">
                    <p className="text-lg">Follow these steps to connect your local machine to Boundary:</p>

                    <div className="bg-gray-100 p-4 rounded">
                      <p className="font-bold mb-2">Step 1: Open PowerShell</p>
                      <ul className="list-disc ml-6 space-y-1">
                        <li>Press <strong>Windows Key + R</strong>, type <code>powershell</code>, press Enter</li>
                      </ul>
                    </div>

                    <div className="bg-gray-100 p-4 rounded">
                      <p className="font-bold mb-2">Step 2: Run the bridge</p>
                      <code className="block bg-gray-800 text-white p-3 rounded mt-2">
                        cd Downloads
                        <br />
                        python bridge.py
                      </code>
                    </div>

                    <div className="bg-gray-100 p-4 rounded">
                      <p className="font-bold mb-2">Step 3: Keep it running</p>
                      <p>Minimize the PowerShell window and start using Boundary!</p>
                      <p className="text-sm text-gray-600 mt-2">
                        The bridge connects your local files to Boundary&apos;s AI.
                        Keep the window open while using Boundary.
                      </p>
                    </div>

                    <div className="flex justify-end gap-3 mt-6">
                      <button
                        onClick={() => setShowBridgeInfo(false)}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded"
                      >
                        Got it!
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Email Accounts panel */}
            {showEmailAccounts && (
              <DiagnosticErrorBoundary componentName="Email Accounts">
                <EmailAccountsModal onClose={() => setShowEmailAccounts(false)} />
              </DiagnosticErrorBoundary>
            )}
            <div className="bg-white rounded-lg shadow">
              <div className="flex border-b">
                {[
                  { id: "custom", label: "Agents" },
                  { id: "projects", label: "Projects" },
                ].map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => handleTabChange(tab.id)}
                    className={`px-6 py-3 font-medium ${activeTab === tab.id
                      ? "border-b-2 border-blue-500 text-blue-500"
                      : "text-gray-500 hover:text-gray-700"
                      }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              <div className="min-h-[500px]">
                <DiagnosticErrorBoundary componentName="Content Area">
                  {renderComponents()}
                </DiagnosticErrorBoundary>
              </div>
            </div>
          </div>

          {/* Modal handling with error boundaries */}
          {((editing?.type === "agent" && !isProjectsTab) ||
            (editing?.type === "project" && isProjectsTab)) && (
              <DiagnosticErrorBoundary componentName="Edit Modal">
                <EditAgentModal
                  type={editing.type}
                  data={editing.data}
                  onClose={() => setEditing(null)}
                  onSave={handleSaveEdit}
                />
              </DiagnosticErrorBoundary>
            )}

          {chatting && !isProjectsTab && (
            <DiagnosticErrorBoundary componentName="Chat Modal">
              <AgentChatModal
                agent={chatting}
                messages={getAgentMessages(chatting.id)}
                onClose={() => setChatting(null)}
              />
            </DiagnosticErrorBoundary>
          )}
        </div>
      </DndProvider>
    </DiagnosticErrorBoundary>
  );
}

// Main MyApp component - just wraps everything in ClerkProvider
export default function MyApp({ Component, pageProps }) {
  if (LOCAL_MODE) return <AppContent />;
  return (
    <ClerkProvider {...pageProps}>
      <SignedIn>
        <AppContent />
      </SignedIn>
      <SignedOut>
        <RedirectToSignIn />
      </SignedOut>
    </ClerkProvider>
  );
}