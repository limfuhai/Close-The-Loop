import React from 'react';

class DiagnosticErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    // Update state so the next render will show the fallback UI
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    // You can also log the error to an error reporting service
    console.error(`Error in ${this.props.componentName || 'component'}:`, error, errorInfo);
    this.setState({ errorInfo });
    
    // Optional error reporting service call
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }
  }

  render() {
    if (this.state.hasError) {
      // Customizable fallback UI
      return this.props.fallback ? (
        this.props.fallback(this.state.error, this.state.errorInfo)
      ) : (
        <div className="error-container border-2 border-red-500 p-4 rounded">
          <h3 className="text-xl font-bold text-red-700">
            Error in {this.props.componentName || 'component'}
          </h3>
          <pre className="bg-gray-100 p-3 rounded mt-2 text-sm overflow-auto">
            {this.state.error?.toString()}
          </pre>
          {this.state.errorInfo && (
            <details className="mt-2">
              <summary className="cursor-pointer text-blue-600">Component Stack</summary>
              <pre className="bg-gray-100 p-2 mt-1 text-xs">
                {this.state.errorInfo.componentStack}
              </pre>
            </details>
          )}
          {this.props.children && (
            <div className="mt-4">
              <button 
                onClick={() => this.setState({ hasError: false, error: null, errorInfo: null })}
                className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
              >
                Try Again
              </button>
            </div>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

export default DiagnosticErrorBoundary;