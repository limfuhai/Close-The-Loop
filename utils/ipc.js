/**
 * Utility functions for Electron IPC communication
 * This file provides safe methods to interact with Electron's IPC system
 * and fallbacks when running in a web browser during development
 */

/**
 * Check if the app is running inside Electron
 * @returns {boolean} True if running in Electron, false otherwise
 */
export const isElectron = () => {
    return typeof window !== 'undefined' && 
           typeof window.electron !== 'undefined' && 
           typeof window.electron.getVersion === 'function';
  };
  
  /**
   * Send a message to the Electron main process
   * @param {string} channel - The channel to send the message on
   * @param {any} data - The data to send
   * @returns {void}
   */
  export const sendToMain = (channel, data) => {
    if (isElectron()) {
      window.electron.send(channel, data);
    } else {
      console.log('Not running in Electron, message not sent:', { channel, data });
    }
  };
  
  /**
   * Register a listener for messages from the main process
   * @param {string} channel - The channel to listen on
   * @param {function} callback - The callback function to invoke when a message is received
   * @returns {function} - A cleanup function to remove the listener
   */
  export const listenToMain = (channel, callback) => {
    if (isElectron()) {
      window.electron.receive(channel, callback);
      
      // Return a cleanup function
      return () => {
        window.electron.removeAllListeners(channel);
      };
    }
    return () => {}; // Empty cleanup function when not in Electron
  };
  
  /**
   * Execute a file system operation through Electron
   * Use this for file reads, writes, and other operations that require native access
   * @param {string} operation - The operation type ('read', 'write', 'select', etc.)
   * @param {object} options - Operation-specific options
   * @returns {Promise<any>} - A promise that resolves with the operation result
   */
  export const fileOperation = (operation, options) => {
    return new Promise((resolve, reject) => {
      if (!isElectron()) {
        reject(new Error('File operations are only available in Electron'));
        return;
      }
  
      // Generate a unique ID for this request
      const requestId = `file-op-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      
      // Set up a one-time listener for the response
      const responseHandler = (result) => {
        if (result.error) {
          reject(new Error(result.error));
        } else {
          resolve(result.data);
        }
      };
  
      window.electron.receive('file-result', responseHandler);
      
      // Send the file operation request
      window.electron.send('file-operation', {
        id: requestId,
        operation,
        options
      });
    });
  };
  
  /**
   * Control the Python backend process
   * @param {string} action - The action to perform ('start', 'stop', 'restart')
   * @returns {Promise<boolean>} - A promise that resolves with the operation success
   */
  export const controlPythonBackend = (action) => {
    return new Promise((resolve) => {
      if (!isElectron()) {
        console.log(`Python backend ${action} requested, but not running in Electron`);
        resolve(false);
        return;
      }
  
      const statusHandler = (status) => {
        resolve(status.success);
      };
  
      window.electron.receive('python-status', statusHandler);
      window.electron.send('python-control', { action });
    });
  };