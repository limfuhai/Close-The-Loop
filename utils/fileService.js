import { fileOperation } from './ipc';

export const saveFile = async (file) => {
  if (typeof window !== 'undefined' && window.electron) {
    // Use Electron IPC for file operations
    return await fileOperation('save', { 
      file: file.name,
      content: await file.arrayBuffer(), 
      type: file.type
    });
  } else {
    // Fallback for non-Electron environments
    // Can use WebSocket or API endpoints
    throw new Error('File operations only available in desktop app');
  }
};

export const readFile = async (path) => {
  // Similar implementation with Electron/fallback logic
};