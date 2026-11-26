import { useState } from 'react';
import useStore from '../lib/store';

const EditAgentModal = ({ type, data, onClose, onSave }) => {
    const [editedData, setEditedData] = useState(data || { name: '', initialPrompt: '' });
    const { updateAgent, updateProject, addError } = useStore();
  
    if (!data) return null;
  
    const handleSave = () => {
      if (!editedData.name || 
          (type === 'agent' && !editedData.initialPrompt)) {
        alert('Please fill in all required fields');
        return;
      }
    
      try {
        if (type === 'agent') {
          updateAgent(editedData.id, editedData);
        } else {
          updateProject(editedData.id, editedData);
        }
        onClose();
      } catch (error) {
        addError({
          message: `Failed to update ${type}`,
          timestamp: new Date().toISOString()
        });
      }
    };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white p-6 rounded-lg w-2/3">
        <h2 className="text-xl font-bold mb-4">Edit {type}</h2>
        <div className="space-y-4">
          <div>
            <label className="block mb-1">Name:</label>
            <input
              type="text"
              value={editedData.name}
              onChange={(e) => setEditedData({...editedData, name: e.target.value})}
              className="w-full p-2 border rounded"
            />
          </div>
          {type === 'agent' && (
            <div>
              <label className="block mb-1">Task Instructions:</label>
              <textarea
                value={editedData.initialPrompt}
                onChange={(e) => setEditedData({...editedData, initialPrompt: e.target.value})}
                className="w-full p-2 border rounded h-32"
              />
            </div>
          )}
          <div className="flex justify-end space-x-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
            >
              Save Changes
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default EditAgentModal;