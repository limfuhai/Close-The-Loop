import useStore from "@/lib/store";
import { useEffect, useRef, useState } from "react";

export const useAgentChatModal = ({ agent, messages }) => {
  const [newMessage, setNewMessage] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isUseMultiAgent, setIsUseMultiAgent] = useState(false);
  const [selectedArtifact, setSelectedArtifact] = useState(null);
  const [conversationTone, setConversationTone] = useState("neutral");

  const fileInputRef = useRef(null);
  const chatEndRef = useRef(null);
  const chatInputRef = useRef(null);
  const abortChatControllerRef = useRef(null);

  // Add these to the component's state and props:
  const [orchestratorTask, setOrchestratorTask] = useState(null);

  // Add to useStore destructuring:
  const {
    triggerOrchestrator,
    addAgentMessage,
    addError,
    savePersistentEdit,
    getPersistentEdit,
    sendAgentMessage,
    uploadAgentMessageWithFile,
    startMultiAgentTask,
    startMultiAgentTaskWithFiles,
  } = useStore();

  const isChatInputDisabled = !newMessage.trim() && selectedFiles.length === 0;

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    const savedChat = getPersistentEdit(agent.id, "chat");
    if (savedChat) {
      setNewMessage(savedChat);
    }
  }, [messages, agent.id, getPersistentEdit]);

  useEffect(() => {
    const lastMessage = messages[messages.length - 1];
    if (lastMessage && lastMessage.metadata?.isOrchestratorTask) {
      setOrchestratorTask({
        orchestrationId: lastMessage.metadata.orchestrationId,
        taskId: lastMessage.metadata.taskId,
      });
      // Auto-enable multi-agent mode for orchestrator tasks
      setIsUseMultiAgent(true);
    }
  }, [messages]);

  useEffect(() => {
    const handleLinkClick = (e) => {
      const link = e.target.closest("a");
      if (link && link.href && link.href.startsWith("localfile://")) {
        e.preventDefault();
        const filePath = link.href.replace("localfile://", "");

        if (window.fileSystem && window.fileSystem.openLocalFile) {
          window.fileSystem
            .openLocalFile(filePath)
            .then((result) => {
              if (!result.success) {
                console.error("Failed to open file:", result.error);
              }
            })
            .catch((err) => {
              console.error("Error opening file:", err);
            });
        }
      }
    };

    document.addEventListener("click", handleLinkClick);
    return () => {
      document.removeEventListener("click", handleLinkClick);

      if (abortChatControllerRef.current) {
        abortChatControllerRef.current.abort();
      }
    };
  }, []);

  useEffect(() => {
    if (chatInputRef.current && !isSending) {
      chatInputRef.current.focus();
    }
  }, [isSending]);

  const handleFileSelect = (event) => {
    const files = Array.from(event.target.files || []);
    if (files.length === 0) return;
    setSelectedFiles((prev) => [...prev, ...files]);
  };

  const handleRemoveFile = (fileName) => {
    setSelectedFiles((prev) => prev.filter((file) => file.name !== fileName));
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleSendMessage = async () => {
    if (!newMessage.trim() && selectedFiles.length === 0) return;
    setIsSending(true);

    if (abortChatControllerRef.current) {
      abortChatControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortChatControllerRef.current = controller;

    try {
      // Check if this is a complex request that should trigger orchestrator
      const COMPLEXITY_THRESHOLD = 500;
      const isComplexRequest = newMessage.trim().length > COMPLEXITY_THRESHOLD;

      if (isComplexRequest && isUseMultiAgent && !orchestratorTask) {
        // This is a complex request - trigger orchestrator
        await triggerOrchestrator(
          agent.projectId,
          newMessage.trim(),
          agent.id,
          controller.signal
        );

        // Clear the input but don't send a regular message
        // The orchestrator will send task messages back
        setNewMessage("");
        savePersistentEdit(agent.id, "chat", "");

        // Show feedback to user
        addAgentMessage(agent.id, {
          id: Date.now().toString(),
          agentId: agent.id,
          content:
            "Your complex request has been sent to the orchestrator for task distribution. Tasks will appear shortly...",
          timestamp: new Date().toISOString(),
          sender: "system",
        });

        return;
      }

      // Regular message handling continues...
      if (selectedFiles.length > 0) {
        if (isUseMultiAgent) {
          await startMultiAgentTaskWithFiles(
            newMessage.trim(),
            selectedFiles,
            agent.id,
            conversationTone,
            controller.signal
          );
        } else {
          await uploadAgentMessageWithFile(
            agent.id,
            newMessage.trim(),
            selectedFiles[0],
            conversationTone,
            controller.signal
          );
        }
      } else {
        if (isUseMultiAgent) {
          console.log("Testing hi");
          await startMultiAgentTask(
            newMessage.trim(),
            agent.id,
            conversationTone,
            controller.signal
          );
        } else {
          await sendAgentMessage(
            agent.id,
            newMessage.trim(),
            true,
            conversationTone,
            controller.signal
          );
        }
      }

      // Clear form
      setNewMessage("");
      setSelectedFiles([]);
      savePersistentEdit(agent.id, "chat", "");

      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (error) {
      console.error("Error sending message:", error);
      addError({
        message: "Failed to send message: " + error.message,
        timestamp: new Date().toISOString(),
      });
    } finally {
      setIsSending(false);
      setNewMessage("");
    }
  };

  const handleMessageChange = (e) => {
    const value = e.target.value;
    setNewMessage(value);
    savePersistentEdit(agent.id, "chat", value);
  };

  const handleOnKeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleAbortChat = () => {
    if (abortChatControllerRef.current) {
      abortChatControllerRef.current.abort();
      abortChatControllerRef.current = null;
    }
    setIsSending(false);
  };

  return {
    fileInputRef,
    chatEndRef,
    chatInputRef,
    newMessage,
    selectedArtifact,
    setSelectedArtifact,
    orchestratorTask,
    setOrchestratorTask,
    conversationTone,
    setConversationTone,
    selectedFiles,
    isSending,
    isUseMultiAgent,
    isChatInputDisabled,
    setIsUseMultiAgent,
    handleFileSelect,
    handleRemoveFile,
    handleMessageChange,
    handleSendMessage,
    handleOnKeydown,
    handleAbortChat,
  };
};
