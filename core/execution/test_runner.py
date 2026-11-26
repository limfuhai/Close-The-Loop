"""
Test runner for Playwright-based automated testing.
Manages test execution, result capture, and JSON output storage.
"""

import os
import json
import subprocess
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path
import re

class PlaywrightTestRunner:
    """
    Manages Playwright test lifecycle: creation, execution, and result collection.
    """
    
    def __init__(self):
        """Initialize the test runner and create necessary directories."""
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Set up directory structure
        self.base_dir = os.path.join(os.getcwd(), 'opex_scripts')
        self.tests_dir = os.path.join(self.base_dir, 'tests')
        self.outputs_dir = os.path.join(self.base_dir, 'outputs')
        self.screenshots_dir = os.path.join(self.outputs_dir, 'screenshots')
        
        # Create directories
        for directory in [self.tests_dir, self.outputs_dir, self.screenshots_dir]:
            os.makedirs(directory, exist_ok=True)
            
        self.logger.info(f"Test runner initialized with base directory: {self.base_dir}")
        
    def save_test_script(self, code: str, test_name: str = "test") -> Dict[str, Any]:
        """
        Save the generated test code to a Python file.
        
        Args:
            code: Python code containing Playwright tests
            test_name: Base name for the test file
            
        Returns:
            Dictionary with file information
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:21]
        filename = f"playwright_{test_name}_{timestamp}.py"
        filepath = os.path.join(self.tests_dir, filename)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(code)
            
            self.logger.info(f"Test script saved: {filepath}")
            return {
                "status": "saved",
                "filename": filename,
                "filepath": filepath
            }
        except Exception as e:
            self.logger.error(f"Failed to save test script: {str(e)}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    def execute_test(self, filepath: str, timeout: int = 60) -> Dict[str, Any]:
        """
        Execute a Playwright test script and capture results.
        
        Args:
            filepath: Path to the test script
            timeout: Maximum execution time in seconds
            
        Returns:
            Dictionary containing execution results and captured output
        """
        try:
            # Run the test script using Python
            result = subprocess.run(
                ['python', filepath],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.outputs_dir  # Run from outputs dir so files save there
            )
            
            # Parse the output for test results
            output = result.stdout
            error = result.stderr
            
            # Extract test results from output
            test_results = self._parse_test_output(output, error)
            
            # Save results to JSON
            json_filename = self._save_json_results(test_results, filepath)
            
            return {
                "status": "completed",
                "exit_code": result.returncode,
                "output": output,
                "error": error,
                "test_results": test_results,
                "json_file": json_filename,
                "execution_time": datetime.now().isoformat()
            }
            
        except subprocess.TimeoutExpired:
            self.logger.error(f"Test execution timed out after {timeout} seconds")
            return {
                "status": "timeout",
                "error": f"Test execution exceeded {timeout} seconds",
                "test_results": {"status": "timeout", "tests": []}
            }
        except Exception as e:
            self.logger.error(f"Test execution failed: {str(e)}")
            return {
                "status": "error",
                "error": str(e),
                "test_results": {"status": "error", "message": str(e)}
            }
    
    def _parse_test_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """
        Parse test output to extract structured results.
        
        Args:
            stdout: Standard output from test execution
            stderr: Standard error from test execution
            
        Returns:
            Structured test results
        """
        results = {
            "status": "unknown",
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "tests": [],
            "errors": []
        }
        
        # Look for test result patterns in output
        lines = stdout.split('\n')
        
        for line in lines:
            # Look for test status lines (customize based on output format)
            if "PASS:" in line:
                results["passed"] += 1
                test_name = line.split("PASS:")[1].strip()
                results["tests"].append({
                    "name": test_name,
                    "status": "passed"
                })
            elif "FAIL:" in line:
                results["failed"] += 1
                test_name = line.split("FAIL:")[1].strip()
                results["tests"].append({
                    "name": test_name,
                    "status": "failed"
                })
            elif "ERROR:" in line:
                results["errors"].append(line)
            elif "Screenshot saved:" in line:
                # Capture screenshot paths
                if "screenshots" not in results:
                    results["screenshots"] = []
                results["screenshots"].append(line.split("Screenshot saved:")[1].strip())
        
        # Parse any JSON output if present
        try:
            json_match = re.search(r'TEST_RESULTS_JSON:\s*({.*})', stdout, re.DOTALL)
            if json_match:
                json_data = json.loads(json_match.group(1))
                results.update(json_data)
        except:
            pass  # No JSON output or invalid JSON
        
        # Determine overall status
        results["total_tests"] = results["passed"] + results["failed"] + results["skipped"]
        if results["failed"] > 0 or results["errors"]:
            results["status"] = "failed"
        elif results["passed"] > 0:
            results["status"] = "passed"
        
        # Include any error output
        if stderr:
            results["stderr"] = stderr
            if "Traceback" in stderr:
                results["status"] = "error"
                results["errors"].append("Python error occurred - see stderr for details")
        
        return results
    
    def _save_json_results(self, test_results: Dict[str, Any], test_filepath: str) -> str:
        """
        Save test results to a JSON file.
        
        Args:
            test_results: Structured test results
            test_filepath: Original test file path for naming
            
        Returns:
            Path to the saved JSON file
        """
        # Generate filename based on test file
        test_name = Path(test_filepath).stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_filename = f"test_results_{test_name}_{timestamp}.json"
        json_filepath = os.path.join(self.outputs_dir, json_filename)
        
        try:
            with open(json_filepath, 'w', encoding='utf-8') as f:
                json.dump(test_results, f, indent=2)
            
            self.logger.info(f"Test results saved to: {json_filepath}")
            return json_filename
        except Exception as e:
            self.logger.error(f"Failed to save JSON results: {str(e)}")
            return ""
    
    def run_test_from_code(self, code: str, test_name: str = "test", timeout: int = 60) -> Dict[str, Any]:
        """
        Complete workflow: save code, execute test, return results.
        
        Args:
            code: Python Playwright test code
            test_name: Name for the test
            timeout: Execution timeout
            
        Returns:
            Complete execution results including file paths and test outcomes
        """
        # Save the test script
        save_result = self.save_test_script(code, test_name)
        if save_result["status"] == "error":
            return save_result
        
        # Execute the test
        execution_result = self.execute_test(save_result["filepath"], timeout)
        
        # Combine results
        return {
            **execution_result,
            "test_file": save_result["filename"],
            "test_filepath": save_result["filepath"]
        }
    
    def cleanup_old_tests(self, days: int = 7):
        """
        Remove test files older than specified days.
        
        Args:
            days: Number of days to keep test files
        """
        cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)
        
        for directory in [self.tests_dir, self.screenshots_dir]:
            for file in Path(directory).glob("*"):
                if file.is_file() and file.stat().st_mtime < cutoff_time:
                    try:
                        file.unlink()
                        self.logger.info(f"Deleted old file: {file}")
                    except Exception as e:
                        self.logger.error(f"Failed to delete {file}: {str(e)}")