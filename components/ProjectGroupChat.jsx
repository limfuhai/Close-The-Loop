import { FunctionErrorBoundary } from '@/components/ErrorBoundaries';
import React, { useState, useRef, useEffect } from 'react';
import { X, MessageCircle, Send, Users, Bot } from 'lucide-react';
import useStore from '../lib/store';

const MessageBubble = ({ msg, agents }) => {
  const isSystem = msg.sender_name === 'system';
  const isUser = msg.sender_name === 'user';
  const isGroupContext = msg.type === 'group_chat_context';

  return (
    <div className={`mb-4 ${isUser ? 'flex justify-end' : ''}`}>
      <div className={`p-3 rounded-lg shadow-sm max-w-[80%] ${
        isSystem    ? 'bg-gray-100 text-gray-500 text-sm italic' :
        isUser      ? 'bg-blue-50 ml-auto' :
        isGroupContext ? 'bg-yellow-50 border border-yellow-200' :
        'bg-white border'
      }`}>
        {!isSystem && !isUser && (
          <div className="flex items-center gap-1 text-sm font-medium text-blue-600 mb-1">
            <Bot size={12} />
            {msg.sender_name}
          </div>
        )}
        <div className="message-content text-sm">{msg.content}</div>
        <div className="text-xs text-gray-400 mt-1">
          {new Date(msg.created_at).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
};

const GroupChatPanel = ({ groupChat, onClose }) => {
  const [newMessage, setNewMessage] = useState('');
  const messageEndRef = useRef(null);
  const { getV4GroupChatMessages, addV4GroupChatMessage } = useStore();

  const messages = getV4GroupChatMessages(groupChat.id);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = () => {
    if (!newMessage.trim()) return;
    const message = {
      id: Date.now().toString(),
      group_chat_id: groupChat.id,
      sender_id: 'user',
      sender_name: 'user',
      content: newMessage,
      created_at: new Date().toISOString()
    };
    addV4GroupChatMessage(groupChat.id, message);
    // Felix: POST to /api/v4/group-chats/{groupChat.id}/messages
    setNewMessage('');
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b flex justify-between items-center bg-gray-50">
        <div>
          <div className="font-semibold text-sm">{groupChat.title}</div>
          <div className="text-xs text-gray-500">
            {groupChat.member_ids.length} members
          </div>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
          <X size={16} />
        </button>
      </div>

      <div className="flex-grow p-3 overflow-y-auto bg-gray-50 space-y-2">
        {messages.length === 0 ? (
          <div className="text-center text-gray-400 text-sm py-8">
            No messages yet
          </div>
        ) : (
          messages.map(msg => (
            <MessageBubble key={msg.id} msg={msg} />
          ))
        )}
        <div ref={messageEndRef} />
      </div>

      <div className="p-3 border-t flex gap-2">
        <input
          type="text"
          value={newMessage}
          onChange={e => setNewMessage(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          placeholder="Post to group chat..."
          className="flex-grow p-2 text-sm border rounded"
        />
        <button
          onClick={handleSend}
          className="px-3 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          <Send size={14} />
        </button>
      </div>
    </div>
  );
};

const ProjectGroupChat = ({ project, onClose }) => {
  const [selectedChat, setSelectedChat] = useState(null);
  const { v4GroupChats } = useStore();

  // Felix: replace this with live query from group_chat_registry where project_id = project.id
  const projectChats = Object.values(v4GroupChats).filter(
    chat => chat.metadata?.project_id === project.id
  );

  return (
    <FunctionErrorBoundary componentName={`Project Group Chat: ${project.name}`}>
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div className="bg-white w-3/4 h-3/4 rounded-lg flex overflow-hidden">

          {/* Left sidebar: list of group chats */}
          <div className="w-1/3 border-r flex flex-col">
            <div className="p-4 border-b flex justify-between items-center">
              <div className="flex items-center gap-2">
                <MessageCircle className="w-5 h-5 text-blue-500" />
                <h2 className="font-bold">{project.name}</h2>
              </div>
              <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
                <X size={18} />
              </button>
            </div>

            <div className="flex-grow overflow-y-auto">
              {projectChats.length === 0 ? (
                <div className="p-4 text-sm text-gray-400 text-center">
                  No group chats yet. They appear here when agents spawn them.
                </div>
              ) : (
                projectChats.map(chat => (
                  <button
                    key={chat.id}
                    onClick={() => setSelectedChat(chat)}
                    className={`w-full text-left p-3 border-b hover:bg-gray-50 ${
                      selectedChat?.id === chat.id ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''
                    }`}
                  >
                    <div className="font-medium text-sm">{chat.title}</div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {chat.description}
                    </div>
                    <div className="flex items-center gap-1 text-xs text-gray-400 mt-1">
                      <Users size={10} />
                      {chat.member_ids.length} agents
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>

          {/* Right panel: selected chat messages */}
          <div className="flex-grow flex flex-col">
            {selectedChat ? (
              <GroupChatPanel
                groupChat={selectedChat}
                onClose={() => setSelectedChat(null)}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                Select a group chat to view messages
              </div>
            )}
          </div>

        </div>
      </div>
    </FunctionErrorBoundary>
  );
};

export default ProjectGroupChat;