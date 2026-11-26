# build_app_backend.py
"""
Backend App Building Execution Module
Handles the pipeline for building Flask backend applications from natural language descriptions.
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


class BackendAppBuilder:
    """
    Main orchestrator for backend app building functionality.
    Manages the pipeline from request to deployable Flask backend.
    """
    
    def __init__(self, output_base_dir: str = "generated_backends"):
        """
        Initialize the Backend App Builder.
        
        Args:
            output_base_dir: Base directory for generated backends
        """
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(exist_ok=True)
        logger.info(f"Initialized Backend App Builder with output directory: {self.output_base_dir}")
    
    def build_backend(self, code: str, project_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute backend builder code and organize the output.
        
        Args:
            code: Python code that generates the API backend files
            project_name: Optional name for the backend project
            
        Returns:
            Dictionary with build results and file paths
        """
        # Generate project name if not provided
        if not project_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            project_name = f"backend_{timestamp}"
        
        # Create project directory
        project_dir = self.output_base_dir / project_name
        project_dir.mkdir(exist_ok=True)
        
        logger.info(f"Building backend project: {project_name}")
        
        # Create temporary Python file for execution
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file.write(code)
            temp_script = temp_file.name
        
        try:
            # Execute the backend builder script
            result = subprocess.run(
                ['python', temp_script],
                cwd=str(project_dir),
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Collect created files
            created_files = list(project_dir.glob('**/*'))
            file_list = [str(f.relative_to(project_dir)) for f in created_files if f.is_file()]
            
            # Parse execution results
            if result.returncode == 0:
                logger.info(f"Successfully built backend with {len(file_list)} files")
                
                # Read key files for summary
                summary = self._generate_backend_summary(project_dir)
                
                return {
                    'status': 'success',
                    'project_name': project_name,
                    'project_dir': str(project_dir),
                    'files_created': file_list,
                    'summary': summary,
                    'output': result.stdout,
                    'instructions': self._generate_setup_instructions(project_dir)
                }
            else:
                logger.error(f"Backend build failed: {result.stderr}")
                return {
                    'status': 'error',
                    'project_name': project_name,
                    'error': result.stderr or result.stdout,
                    'returncode': result.returncode
                }
                
        except subprocess.TimeoutExpired:
            logger.error("Backend build timed out")
            return {
                'status': 'error',
                'project_name': project_name,
                'error': 'Build process timed out after 30 seconds'
            }
        except Exception as e:
            logger.error(f"Backend build error: {str(e)}")
            return {
                'status': 'error',
                'project_name': project_name,
                'error': str(e)
            }
        finally:
            # Clean up temporary file
            if os.path.exists(temp_script):
                os.unlink(temp_script)
    
    def _generate_backend_summary(self, project_dir: Path) -> Dict[str, Any]:
        """
        Generate a summary of the created backend.
        
        Args:
            project_dir: Path to the backend project directory
            
        Returns:
            Summary dictionary with backend details
        """
        summary = {
            'structure': {},
            'endpoints': [],
            'models': [],
            'features': []
        }
        
        # Check for key files
        key_files = ['app.py', 'models.py', 'auth.py', 'api.py', 'requirements.txt']
        for file in key_files:
            file_path = project_dir / file
            if file_path.exists():
                summary['structure'][file] = True
                
                # Extract basic info from files
                if file == 'models.py':
                    with open(file_path, 'r') as f:
                        content = f.read()
                        if 'class User' in content:
                            summary['models'].append('User')
                        # Find other models
                        import re
                        models = re.findall(r'class (\w+)\(.*Model.*\)', content)
                        summary['models'].extend([m for m in models if m != 'User'])
                
                elif file == 'requirements.txt':
                    with open(file_path, 'r') as f:
                        summary['dependencies'] = [line.strip() for line in f if line.strip()]
        
        # Determine features based on files present
        if 'auth.py' in summary['structure']:
            summary['features'].append('JWT Authentication')
        if 'api.py' in summary['structure']:
            summary['features'].append('CRUD Operations')
        if 'models.py' in summary['structure']:
            summary['features'].append('SQLAlchemy ORM')
        
        return summary
    
    def _generate_setup_instructions(self, project_dir: Path) -> str:
        """
        Generate setup instructions for the backend.
        
        Args:
            project_dir: Path to the backend project directory
            
        Returns:
            Setup instructions as a string
        """
        instructions = f"""
## Backend Setup Instructions

1. Navigate to the project directory:
   ```bash
   cd {project_dir}
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\\Scripts\\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Initialize the database:
   ```bash
   python -c "from app import app, db; app.app_context().push(); db.create_all()"
   ```

5. Run the backend:
   ```bash
   python app.py
   ```

The API will be available at http://localhost:5000

## Default Endpoints:
- POST /auth/register - Register new user
- POST /auth/login - Login and receive JWT token
- GET /api/items - Get all items (requires auth)
- POST /api/items - Create new item (requires auth)
- PUT /api/items/<id> - Update item (requires auth)
- DELETE /api/items/<id> - Delete item (requires auth)

## Testing:
Use tools like Postman or curl to test the endpoints.
Include the JWT token in the Authorization header: `Bearer <token>`
"""
        return instructions
    
    def validate_backend(self, project_dir: str) -> Dict[str, Any]:
        """
        Validate that the generated backend has all required components.
        
        Args:
            project_dir: Path to the backend project directory
            
        Returns:
            Validation results
        """
        project_path = Path(project_dir)
        validation = {
            'is_valid': True,
            'missing_files': [],
            'warnings': []
        }
        
        # Check for required files
        required_files = ['app.py', 'requirements.txt']
        for file in required_files:
            if not (project_path / file).exists():
                validation['is_valid'] = False
                validation['missing_files'].append(file)
        
        # Check for recommended files
        recommended_files = ['models.py', 'auth.py', 'api.py']
        for file in recommended_files:
            if not (project_path / file).exists():
                validation['warnings'].append(f"Recommended file '{file}' is missing")
        
        return validation