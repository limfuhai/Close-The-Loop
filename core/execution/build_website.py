# build_website.py
"""
Website Building Execution Module
Handles the pipeline for building websites from natural language descriptions.
"""

import os
import json
import logging
import subprocess
import webbrowser
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class WebsiteBuilder:
    """
    Main orchestrator for website building functionality.
    Manages the pipeline from request to deployed website.
    """
    
    def __init__(self, output_base_dir: str = "generated_websites"):
        """
        Initialize the Website Builder.
        
        Args:
            output_base_dir: Base directory for generated websites
        """
        self.output_base_dir = Path(output_base_dir)
        self.output_base_dir.mkdir(exist_ok=True)
        logger.info(f"Initialized Website Builder with output directory: {self.output_base_dir}")
    
    def build_website(self, code: str, project_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute website builder code and organize the output.
        
        Args:
            code: Python code that generates the website
            project_name: Optional project name
            
        Returns:
            Dictionary with build results
        """
        try:
            # Generate project name if not provided
            if not project_name:
                project_name = f"website_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Create project directory
            project_dir = self.output_base_dir / project_name
            project_dir.mkdir(exist_ok=True)
            
            logger.info(f"Building website: {project_name}")
            
            # Save the generator script
            generator_file = project_dir / "website_generator.py"
            generator_file.write_text(code, encoding='utf-8')
            
            # Execute the code to create website files
            result = self._execute_generator(code, project_dir)
            
            if result['success']:
                # Create README for the project
                self._create_readme(project_dir, project_name)
                
                # Open in browser if index.html exists
                index_file = project_dir / "website_output" / "index.html"
                if not index_file.exists():
                    index_file = project_dir / "index.html"
                
                if index_file.exists():
                    webbrowser.open(f"file://{index_file.absolute()}")
                    logger.info(f"Opened website in browser: {index_file}")
                
                return {
                    'status': 'success',
                    'project_name': project_name,
                    'project_dir': str(project_dir),
                    'files_created': result['files'],
                    'message': f"Website '{project_name}' successfully created!"
                }
            else:
                return {
                    'status': 'error',
                    'project_name': project_name,
                    'error': result.get('error', 'Unknown error'),
                    'message': "Failed to build website"
                }
                
        except Exception as e:
            logger.error(f"Error building website: {str(e)}")
            return {
                'status': 'error',
                'error': str(e),
                'message': "An error occurred while building the website"
            }
    
    def _execute_generator(self, code: str, project_dir: Path) -> Dict[str, Any]:
        """
        Execute the generator code to create website files.
        
        Args:
            code: Python code to execute
            project_dir: Directory to create files in
            
        Returns:
            Execution result dictionary
        """
        try:
            # Write script to project directory
            script_path = project_dir / "temp_generator.py"
            script_path.write_text(code, encoding='utf-8')
            
            # Execute the script
            result = subprocess.run(
                ['python', str(script_path)],
                capture_output=True,
                text=True,
                cwd=str(project_dir),
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"Script execution failed: {result.stderr}")
                return {
                    'success': False,
                    'error': result.stderr
                }
            
            # Find created files
            files_created = []
            
            # Check in website_output subdirectory first
            website_output_dir = project_dir / "website_output"
            if website_output_dir.exists():
                for file in website_output_dir.glob("*"):
                    if file.is_file():
                        files_created.append(str(file.name))
            
            # Also check in project directory
            for extension in ['*.html', '*.css', '*.js']:
                for file in project_dir.glob(extension):
                    files_created.append(str(file.name))
            
            # Clean up temp script
            script_path.unlink(missing_ok=True)
            
            return {
                'success': True,
                'files': files_created,
                'output': result.stdout
            }
            
        except subprocess.TimeoutExpired:
            logger.error("Script execution timed out")
            return {
                'success': False,
                'error': "Script execution timed out after 30 seconds"
            }
        except Exception as e:
            logger.error(f"Error executing generator: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _create_readme(self, project_dir: Path, project_name: str):
        """
        Create a README file for the project.
        
        Args:
            project_dir: Project directory
            project_name: Name of the project
        """
        readme_content = f"""# {project_name}

## Generated Website
This website was automatically generated by OpexCoder Website Builder.

### Generated Files
- index.html - Main HTML file
- styles.css - Stylesheet  
- script.js - JavaScript functionality

### Running the Website
1. Open index.html directly in a browser, or
2. Run `python -m http.server 8000` in the website_output directory
3. Navigate to http://localhost:8000

### Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        readme_file = project_dir / "README.md"
        readme_file.write_text(readme_content, encoding='utf-8')
        logger.info("Created README.md")


# Convenience function for simple website building
def build_website_from_code(code: str, project_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a website from generated Python code.
    
    Args:
        code: Python code that creates website files
        project_name: Optional project name
        
    Returns:
        Build result dictionary
    """
    builder = WebsiteBuilder()
    return builder.build_website(code, project_name)


# Test function
if __name__ == "__main__":
    # Test with a simple website generator
    test_code = '''
import os
from pathlib import Path

# Create output directory
output_dir = Path("website_output")
output_dir.mkdir(exist_ok=True)

# HTML content
html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Website</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <h1>Welcome to the Test Website</h1>
    <p>This is a test of the website builder.</p>
    <script src="script.js"></script>
</body>
</html>"""

# CSS content
css_content = """body {
    font-family: Arial, sans-serif;
    margin: 0;
    padding: 20px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
}

h1 {
    text-align: center;
}"""

# JavaScript content
js_content = """console.log('Website loaded successfully!');"""

# Write files
(output_dir / "index.html").write_text(html_content, encoding="utf-8")
(output_dir / "styles.css").write_text(css_content, encoding="utf-8")  
(output_dir / "script.js").write_text(js_content, encoding="utf-8")

print("Website created successfully!")
'''
    
    builder = WebsiteBuilder()
    result = builder.build_website(test_code, "test_website")
    print(result)