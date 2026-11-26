# build_app_frontend.py
"""
Frontend App Building Execution Module
Handles the pipeline for building React applications from natural language descriptions.
Creates beautiful, modern React apps with routing and data management.
"""

import os
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class FrontendAppBuilder:
    """
    Main orchestrator for React app building functionality.
    Manages the pipeline from request to deployable React application.
    """
    
    def __init__(self, output_base_dir: str = "generated_apps"):
        """
        Initialize the Frontend App Builder.
        
        Args:
            output_base_dir: Base directory for generated applications
        """
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(exist_ok=True)
        logger.info(f"Initialized Frontend App Builder with output directory: {self.output_base_dir}")
    
    def build_app(self, code: str, project_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute React app builder code and organize the output.
        
        Args:
            code: Python code that generates the React application
            project_name: Optional project name
            
        Returns:
            Dictionary with build results
        """
        try:
            # Generate project name if not provided
            if not project_name:
                project_name = f"react_app_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Create project directory
            project_dir = self.output_base_dir / project_name
            project_dir.mkdir(exist_ok=True)
            
            logger.info(f"Building React app: {project_name}")
            
            # Save the generator script
            generator_file = project_dir / "app_generator.py"
            generator_file.write_text(code, encoding='utf-8')
            
            # Execute the code to create React app files
            result = self._execute_generator(code, project_dir)
            
            if result['success']:
                # Create README for the project
                self._create_readme(project_dir, project_name)
                
                # Check if package.json was created
                app_dir = project_dir / "app_frontend"
                package_json = app_dir / "package.json"
                
                if package_json.exists():
                    logger.info(f"React app structure created at: {app_dir}")
                    
                    # Optionally install dependencies (can be disabled for speed)
                    if self._should_install_deps():
                        self._install_dependencies(app_dir)
                
                return {
                    'status': 'success',
                    'project_name': project_name,
                    'project_dir': str(project_dir),
                    'app_dir': str(app_dir),
                    'files_created': result['files'],
                    'message': f"React app '{project_name}' successfully created!",
                    'instructions': "Run 'npm install' then 'npm start' in the app_frontend directory"
                }
            else:
                return {
                    'status': 'error',
                    'project_name': project_name,
                    'project_dir': str(project_dir),
                    'error': result.get('error', 'Unknown error'),
                    'message': f"Failed to create React app: {result.get('error', 'Unknown error')}"
                }
                
        except Exception as e:
            logger.error(f"Error building React app: {str(e)}")
            return {
                'status': 'error',
                'error': str(e),
                'message': f"Error building React app: {str(e)}"
            }
    
    def _execute_generator(self, code: str, project_dir: Path) -> Dict[str, Any]:
        """
        Execute the generator code to create React app files.
        
        Args:
            code: Python code to execute
            project_dir: Directory to run the code in
            
        Returns:
            Execution result with success status and created files
        """
        try:
            # Create a temporary file for the code
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name
            
            # Execute the code in the project directory
            result = subprocess.run(
                ['python', temp_file],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Clean up temp file
            os.unlink(temp_file)
            
            if result.returncode == 0:
                # Scan for created files
                created_files = self._scan_created_files(project_dir)
                logger.info(f"Generator created {len(created_files)} files")
                
                return {
                    'success': True,
                    'files': created_files,
                    'output': result.stdout
                }
            else:
                logger.error(f"Generator failed: {result.stderr}")
                return {
                    'success': False,
                    'error': result.stderr or result.stdout,
                    'files': []
                }
                
        except subprocess.TimeoutExpired:
            logger.error("Generator execution timed out")
            return {
                'success': False,
                'error': 'Execution timed out after 30 seconds',
                'files': []
            }
        except Exception as e:
            logger.error(f"Generator execution error: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'files': []
            }
    
    def _scan_created_files(self, project_dir: Path) -> List[str]:
        """
        Scan project directory for created files.
        
        Args:
            project_dir: Directory to scan
            
        Returns:
            List of created file paths
        """
        created_files = []
        app_dir = project_dir / "app_frontend"
        
        if app_dir.exists():
            for file_path in app_dir.rglob('*'):
                if file_path.is_file():
                    relative_path = file_path.relative_to(project_dir)
                    created_files.append(str(relative_path))
        
        return created_files
    
    def _should_install_deps(self) -> bool:
        """
        Check if dependencies should be auto-installed.
        
        Returns:
            Boolean indicating if deps should be installed
        """
        # Can be configured via environment variable
        return os.getenv('AUTO_INSTALL_DEPS', 'false').lower() == 'true'
    
    def _install_dependencies(self, app_dir: Path) -> bool:
        """
        Install npm dependencies for the React app.
        
        Args:
            app_dir: Directory containing package.json
            
        Returns:
            Success status
        """
        try:
            logger.info("Installing npm dependencies...")
            result = subprocess.run(
                ['npm', 'install'],
                cwd=str(app_dir),
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0:
                logger.info("Dependencies installed successfully")
                return True
            else:
                logger.warning(f"Dependency installation failed: {result.stderr}")
                return False
                
        except Exception as e:
            logger.warning(f"Could not install dependencies: {str(e)}")
            return False
    
    def _create_readme(self, project_dir: Path, project_name: str):
        """
        Create a README file for the generated React app.
        
        Args:
            project_dir: Project directory
            project_name: Name of the project
        """
        readme_content = f"""# {project_name}

## Generated React Application
This React application was automatically generated by OpexCoder Frontend App Builder.

### Features
- ✅ Modern, responsive design with gradients and animations
- ✅ React Router for navigation
- ✅ Data display and management interface
- ✅ API integration with axios (ready to connect to backend)
- ✅ Professional UI components
- ✅ Mobile-responsive layout

### Generated Files
- **package.json** - Dependencies and scripts
- **src/App.js** - Main application component with routing
- **src/pages/HomePage.js** - Landing/dashboard page
- **src/pages/DataList.js** - Data management interface
- **src/services/api.js** - API service configuration
- **src/index.js** - Application entry point
- **src/App.css** - Modern styling with gradients

### Getting Started

1. Navigate to the app directory:
   ```bash
   cd app_frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm start
   ```

4. Open http://localhost:3000 in your browser

### Configuration

Update the API endpoint in `src/services/api.js` to connect to your backend:
```javascript
const API_BASE_URL = 'http://localhost:5000/api';
```

### Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        readme_file = project_dir / "README.md"
        readme_file.write_text(readme_content, encoding='utf-8')
        logger.info("Created README.md")


# Convenience function for simple React app building
def build_react_app_from_code(code: str, project_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a React application from generated Python code.
    
    Args:
        code: Python code that creates React app files
        project_name: Optional project name
        
    Returns:
        Build result dictionary
    """
    builder = FrontendAppBuilder()
    return builder.build_app(code, project_name)


# Test function
if __name__ == "__main__":
    # Test with a minimal React app generator
    test_code = '''
import os
from pathlib import Path

# Create app directory
app_dir = Path("app_frontend")
app_dir.mkdir(exist_ok=True)
src_dir = app_dir / "src"
src_dir.mkdir(exist_ok=True)
pages_dir = src_dir / "pages"
pages_dir.mkdir(exist_ok=True)

# Package.json
package_json = """{
  "name": "test-react-app",
  "version": "0.1.0",
  "private": true,
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.8.0",
    "axios": "^1.3.0",
    "react-scripts": "5.0.1"
  },
  "scripts": {
    "start": "react-scripts start",
    "build": "react-scripts build"
  },
  "browserslist": {
    "production": [">0.2%", "not dead", "not op_mini all"],
    "development": ["last 1 chrome version", "last 1 firefox version", "last 1 safari version"]
  }
}"""

# Simple App.js
app_js = """import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import HomePage from './pages/HomePage';
import DataList from './pages/DataList';
import './App.css';

function App() {
  return (
    <BrowserRouter>
      <div className="App">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/data" element={<DataList />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;"""

# HomePage.js
home_page = """import React from 'react';
import { Link } from 'react-router-dom';

function HomePage() {
  return (
    <div className="home-container">
      <h1>Welcome to Your App</h1>
      <p>A beautiful React application</p>
      <Link to="/data" className="nav-button">View Data</Link>
    </div>
  );
}

export default HomePage;"""

# DataList.js
data_list = """import React, { useState } from 'react';
import { Link } from 'react-router-dom';

function DataList() {
  const [items, setItems] = useState([
    { id: 1, name: 'Item 1', description: 'First item' },
    { id: 2, name: 'Item 2', description: 'Second item' }
  ]);
  
  return (
    <div className="data-container">
      <h1>Data Management</h1>
      <Link to="/" className="nav-button">Back to Home</Link>
      <div className="items-grid">
        {items.map(item => (
          <div key={item.id} className="item-card">
            <h3>{item.name}</h3>
            <p>{item.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default DataList;"""

# App.css
app_css = """body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
}

.App {
  text-align: center;
  padding: 20px;
}

.home-container, .data-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 40px 20px;
}

h1 {
  color: white;
  font-size: 3rem;
  margin-bottom: 20px;
}

.nav-button {
  display: inline-block;
  padding: 12px 24px;
  background: white;
  color: #667eea;
  text-decoration: none;
  border-radius: 8px;
  font-weight: bold;
  transition: transform 0.2s;
}

.nav-button:hover {
  transform: translateY(-2px);
}

.items-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 20px;
  margin-top: 30px;
}

.item-card {
  background: white;
  padding: 20px;
  border-radius: 12px;
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}"""

# Write files
(app_dir / "package.json").write_text(package_json, encoding="utf-8")
(src_dir / "App.js").write_text(app_js, encoding="utf-8")
(pages_dir / "HomePage.js").write_text(home_page, encoding="utf-8")
(pages_dir / "DataList.js").write_text(data_list, encoding="utf-8")
(src_dir / "App.css").write_text(app_css, encoding="utf-8")

print("React app structure created successfully!")
'''
    
    builder = FrontendAppBuilder()
    result = builder.build_app(test_code, "test_react_app")
    print(json.dumps(result, indent=2))