import React from 'react';
import DiagnosticErrorBoundary from './DiagnosticErrorBoundary';

function FunctionErrorBoundary({ 
  children, 
  componentName,
  onError,
  fallback 
}) {
  return (
    <DiagnosticErrorBoundary 
      componentName={componentName}
      onError={onError}
      fallback={fallback}
    >
      {children}
    </DiagnosticErrorBoundary>
  );
}

export default FunctionErrorBoundary;