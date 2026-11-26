# file_utilities.py
import os
import logging
from pathlib import Path
import mimetypes

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_text_from_pdf(file_path, max_pages=20):
    """Extract text from PDF files"""
    try:
        import PyPDF2
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            num_pages = len(reader.pages)
            
            # Limit to max_pages to avoid huge documents
            pages_to_read = min(num_pages, max_pages)
            
            content = []
            for i in range(pages_to_read):
                page = reader.pages[i]
                content.append(page.extract_text())
                
            if num_pages > max_pages:
                content.append(f"\n[{num_pages - max_pages} more pages not shown]")
                
            return "\n\n".join(content)
    except ImportError:
        return "[PDF extraction requires PyPDF2 module]"
    except Exception as e:
        logger.error(f"Error extracting PDF text: {str(e)}")
        return f"[Error extracting PDF text: {str(e)}]"

def extract_text_from_docx(file_path):
    """Extract text from Word documents"""
    try:
        import docx
        doc = docx.Document(file_path)
        content = []
        
        # Extract paragraphs
        for para in doc.paragraphs:
            if para.text.strip():
                content.append(para.text)
                
        # Extract tables
        for table in doc.tables:
            for row in table.rows:
                row_content = [cell.text for cell in row.cells]
                content.append(" | ".join(row_content))
                
        return "\n\n".join(content)
    except ImportError:
        return "[Word document extraction requires python-docx module]"
    except Exception as e:
        logger.error(f"Error extracting Word document text: {str(e)}")
        return f"[Error extracting Word document text: {str(e)}]"

def extract_data_from_xlsx(file_path, max_rows=100, max_sheets=3):
    """Extract data from Excel spreadsheets using pandas"""
    try:
        import pandas as pd
        
        # Read all sheets
        excel_data = pd.read_excel(file_path, sheet_name=None, nrows=max_rows)
        
        content = []
        sheet_names = list(excel_data.keys())
        content.append(f"Sheets: {', '.join(sheet_names)}")
        
        # Process each sheet
        for i, (sheet_name, df) in enumerate(excel_data.items()):
            if i >= max_sheets:
                content.append(f"\n[{len(sheet_names) - max_sheets} more sheets not shown]")
                break
                
            content.append(f"\n## Sheet: {sheet_name}")
            content.append(f"Rows: {len(df)}, Columns: {len(df.columns)}")
            content.append(f"Columns: {', '.join(df.columns)}")
            content.append("\nData:")
            content.append(df.to_string(index=False, max_rows=max_rows))
            
        return "\n".join(content)
        
    except ImportError:
        return "[Excel extraction requires pandas module]"
    except Exception as e:
        return f"[Error extracting Excel data: {str(e)}]"

def extract_text_from_pptx(file_path, max_slides=20):
    """Extract text from PowerPoint presentations"""
    try:
        import pptx
        presentation = pptx.Presentation(file_path)
        content = []
        
        content.append(f"Presentation with {len(presentation.slides)} slides")
        
        # Limit to max_slides
        slides_to_read = min(len(presentation.slides), max_slides)
        
        for i in range(slides_to_read):
            slide = presentation.slides[i]
            content.append(f"\n## Slide {i+1}")
            
            # Extract title
            if slide.shapes.title:
                content.append(f"Title: {slide.shapes.title.text}")
            
            # Extract text from shapes
            texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    texts.append(shape.text)
            
            if texts:
                content.append("\n".join(texts))
            else:
                content.append("[No text content]")
                
        if len(presentation.slides) > max_slides:
            content.append(f"\n[{len(presentation.slides) - max_slides} more slides not shown]")
            
        return "\n".join(content)
    except ImportError:
        return "[PowerPoint extraction requires python-pptx module]"
    except Exception as e:
        logger.error(f"Error extracting PowerPoint text: {str(e)}")
        return f"[Error extracting PowerPoint text: {str(e)}]"

def extract_data_from_csv(file_path, max_rows=100):
    """Extract data from CSV files"""
    try:
        import pandas as pd
        df = pd.read_csv(file_path, nrows=max_rows+1)
        
        content = []
        
        # Get number of rows and columns
        num_rows, num_cols = df.shape
        content.append(f"CSV with {num_rows} rows and {num_cols} columns")
        
        # Get column names
        content.append(f"Columns: {', '.join(df.columns)}")
        
        # Show sample of data (limiting to max_rows)
        if num_rows > max_rows:
            sample_data = df.iloc[:max_rows].to_string(index=False)
            content.append(sample_data)
            content.append(f"\n[{num_rows - max_rows} more rows not shown]")
        else:
            content.append(df.to_string(index=False))
            
        return "\n".join(content)
    except ImportError:
        return "[CSV extraction requires pandas module]"
    except Exception as e:
        logger.error(f"Error extracting CSV data: {str(e)}")
        return f"[Error extracting CSV data: {str(e)}]"

def extract_text_from_text_file(file_path, max_size=5000):
    """Read text files with encoding detection"""
    try:
        # Try to detect encoding
        import chardet
        with open(file_path, 'rb') as f:
            raw_data = f.read(min(1024, os.path.getsize(file_path)))
        
        encoding_result = chardet.detect(raw_data)
        encoding = encoding_result['encoding'] or 'utf-8'
        
        # Read file with detected encoding
        with open(file_path, 'r', encoding=encoding, errors='replace') as f:
            content = f.read(max_size)
            
        if len(content) >= max_size:
            content += "... [content truncated]"
            
        return content
    except Exception as e:
        # Fallback to binary read if text reading fails
        try:
            file_size = os.path.getsize(file_path)
            with open(file_path, 'rb') as f:
                binary_sample = f.read(min(100, file_size))
            return f"[Binary file, first bytes: {binary_sample.hex()[:100]}...]"
        except Exception as be:
            return f"[Error reading file: {str(e)}, binary fallback error: {str(be)}]"

def read_file_content(file_path, max_size=5000):
    """Read content from a file based on its type"""
    try:
        # Initialize mimetypes
        if not mimetypes.inited:
            mimetypes.init()
            
        # Get file extension and mimetype
        ext = os.path.splitext(file_path)[1].lower()
        mime_type = mimetypes.guess_type(file_path)[0]
        
        # Handle different file types
        if ext == '.pdf':
            return extract_text_from_pdf(file_path)
        elif ext in ['.docx', '.doc']:
            return extract_text_from_docx(file_path)
        elif ext in ['.xlsx', '.xls']:
            return extract_data_from_xlsx(file_path)
        elif ext in ['.pptx', '.ppt']:
            return extract_text_from_pptx(file_path)
        elif ext == '.csv':
            return extract_data_from_csv(file_path)
        elif mime_type and mime_type.startswith('text/') or ext in ['.py', '.js', '.html', '.css', '.md', '.json', '.xml']:
            return extract_text_from_text_file(file_path, max_size)
        else:
            # For now, just provide info about other file types
            file_size = os.path.getsize(file_path)
            return f"[Binary file: {os.path.basename(file_path)}, size: {file_size} bytes, type: {mime_type or 'unknown'}]"
            
    except Exception as e:
        logger.error(f"Error processing file {file_path}: {str(e)}")
        return f"[Error processing file: {str(e)}]"