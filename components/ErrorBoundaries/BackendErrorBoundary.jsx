import React, { useState, useEffect } from 'react';
import FunctionErrorBoundary from './FunctionErrorBoundary';

function BackendErrorBoundary({ 
  children, 
  componentName,
  checkConnection,
  retryInterval = 10000,
  onError
}) {
  const [connectionState, setConnectionState] = useState('initializing');
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    let mounted = true;
    let timeoutId = null;

    async function verifyConnection() {
      try {
        setConnectionState('checking');
        await checkConnection();
        if (mounted) {
          setConnectionState('connected');
          setError(null);
        }
      } catch (err) {
        if (mounted) {
          setConnectionState('failed');
          setError(err);
          if (onError) onError(err);
          
          // Schedule retry
          timeoutId = setTimeout(() => {
            if (mounted) {
              setRetryCount(count => count + 1);
              verifyConnection();
            }
          }, retryInterval);
        }
      }
    }

    verifyConnection();

    return () => {
      mounted = false;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [checkConnection, retryInterval, onError]);

  if (connectionState === 'failed') {
    return (
      <div className="backend-error bg-yellow-50 border-l-4 border-yellow-500 p-4">
        <h3 className="font-bold">Backend Connection Failed: {componentName}</h3>
        <p className="mt-1">{error?.message || 'Unknown error'}</p>
        <pre className="mt-2 text-xs bg-yellow-100 p-2 rounded">
          {error?.stack || 'No stack trace available'}
        </pre>
        <div className="mt-2">
          <p className="text-sm text-gray-600">
            Retry count: {retryCount} (Will retry automatically)
          </p>
        </div>
      </div>
    );
  }

  if (connectionState !== 'connected') {
    return (
      <div className="p-4 bg-blue-50 border-l-4 border-blue-500">
        Connecting to backend services for {componentName}...
      </div>
    );
  }

  return (
    <FunctionErrorBoundary componentName={componentName} onError={onError}>
      {children}
    </FunctionErrorBoundary>
  );
}

export default BackendErrorBoundary;