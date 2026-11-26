"""
Code Editor - Handles reading and writing code files for the CodingExecutor
"""

import os
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)


def gather_context(file_paths: List[str]) -> str:
    """
    Read specified files and return their contents with line numbers.
    
    Args:
        file_paths: List of file paths to read
        
    Returns:
        String containing file contents with line numbers
    """
    context = ""
    
    for file_path in file_paths:
        try:
            path = Path(file_path)
            if not path.exists():
                context += f"\n## FILE: {file_path}\n[File not found]\n"
                continue
                
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            context += f"\n## FILE: {file_path}\n"
            context += f"## LINES: {len(lines)}\n"
            
            for i, line in enumerate(lines, 1):
                context += f"{i:4d} | {line}"
                
            context += "\n"
            
        except Exception as e:
            context += f"\n## FILE: {file_path}\n[Error reading file: {str(e)}]\n"
            logger.error(f"Error reading {file_path}: {e}")
    
    return context


def save_fixed_code(code: str, original_filename: str, output_dir: str = "opex_scripts/outputs") -> str:
    """
    Save the fixed code to a new file in the outputs directory.
    
    Args:
        code: The fixed code to save
        original_filename: Original filename (for naming the output)
        output_dir: Directory to save the fixed file
        
    Returns:
        Path to the saved file
    """
    try:
        # Create output directory if it doesn't exist
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = Path(original_filename).stem
        extension = Path(original_filename).suffix
        
        # Create unique filename
        output_filename = f"fixed_{base_name}_{timestamp}{extension}"
        output_file = output_path / output_filename
        
        # Save the fixed code
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(code)
        
        logger.info(f"Saved fixed code to: {output_file}")
        return str(output_file)
        
    except Exception as e:
        logger.error(f"Error saving fixed code: {e}")
        raise


def extract_code_from_response(response: str) -> str:
    """
    Extract code from LLM response, handling various formats.
    
    Args:
        response: The LLM response potentially containing code
        
    Returns:
        Extracted code
    """
    # Look for code blocks
    if "```python" in response:
        start = response.find("```python") + 9
        end = response.find("```", start)
        if end > start:
            return response[start:end].strip()
    
    elif "```" in response:
        start = response.find("```") + 3
        end = response.find("```", start)
        if end > start:
            return response[start:end].strip()
    
    # If no code blocks, assume the entire response is code
    # (especially if it starts with common Python keywords)
    if any(response.strip().startswith(keyword) for keyword in 
           ['import ', 'from ', 'def ', 'class ', '#']):
        return response.strip()
    
    # Default: return as-is
    return response