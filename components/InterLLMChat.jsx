import React, { useState, useRef, useEffect } from 'react';
import { X, Bot, Send } from 'lucide-react';
import useStore from '../lib/store';

const InterLLMChat = ({ onClose, icon }) => {
  const [newMessage, setNewMessage] = useState('');
  const messageEndRef = useRef(null);
  
  const { 
    interLLMChat,
    addInterLLMChatMessage,
    sendWebSocketMessage 
  } = useStore();

  const { messages, connectedInstances } = interLLMChat;

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSendMessage = async () => {
    if (!newMessage.trim()) return;
    
    const message = {
      id: Date.now().toString(),
      content: newMessage,
      sender: 'user',
      timestamp: new Date().toISOString(),
      type: 'user'
    };

    await sendWebSocketMessage({
      type: 'LLM_GROUP_MESSAGE',
      payload: message
    });

    addInterLLMChatMessage(message);
    setNewMessage('');
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white w-2/3 h-3/4 rounded-lg flex flex-col">
        <div className="p-4 border-b flex justify-between items-center">
          <div className="flex items-center gap-2">
            {icon || <Bot className="w-6 h-6 text-green-500" />}
            <div>
              <h2 className="text-xl font-bold">Inter-LLM Chat</h2>
              <p className="text-sm text-gray-500">
                {connectedInstances.length} Connected Instances
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        <div className="flex-grow p-4 overflow-y-auto bg-gray-50">
          {messages.map(msg => (
            <div 
              key={msg.id} 
              className={`mb-4 ${msg.type === 'user' ? 'ml-auto' : ''}`}
            >
              <div className={`p-3 rounded-lg shadow-sm max-w-[80%] ${
                msg.type === 'system' ? 'bg-gray-100' :
                msg.type === 'user' ? 'bg-green-50 ml-auto' :
                'bg-white'
              }`}>
                {msg.type === 'llm' && (
                  <div className="text-sm font-medium text-green-600 mb-1">
                    OpexAssistant #{msg.sender}
                  </div>
                )}
                <div className="message-content">{msg.content}</div>
                <div className="text-xs text-gray-400 mt-1">
                  {new Date(msg.timestamp).toLocaleTimeString()}
                </div>
              </div>
            </div>
          ))}
          <div ref={messageEndRef} />
        </div>

        <div className="p-4 border-t">
          <div className="flex gap-2">
            <input
              type="text"
              value={newMessage}
              onChange={(e) => setNewMessage(e.target.value)}
              placeholder="Type a message to other OpexAssistant instances..."
              className="flex-grow p-2 border rounded"
              onKeyPress={(e) => {
                if (e.key === 'Enter') {
                  handleSendMessage();
                }
              }}
            />
            <button
              onClick={handleSendMessage}
              className="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default InterLLMChat;