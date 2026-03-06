# file: read_zip_files.py

import zipfile  # Module for handling zip archives
from pathlib import Path  # Provides object-oriented file system paths
from collections import defaultdict  # For storing structured line data
import re  # For sanitizing variable names for use as Python variable names

def read_zip_contents(zip_path):
    """
    Reads file contents from a zip archive and stores them in memory.

    Parameters:
    zip_path (str or Path): Path to the zip file

    Returns:
    tuple: (file_data, file_lines, file_vars)
        file_data (dict): Maps original file names to full decoded text content (or None if binary)
        file_lines (dict): Maps original file names to list of lines (text split by line)
        file_vars (dict): Maps sanitized file names (valid Python identifiers) to joined line strings

    Raises:
    FileNotFoundError: If the zip file does not exist at the specified path
    """
    # Ensure the zip file exists before proceeding
    if not Path(zip_path).is_file():
        raise FileNotFoundError(f"Zip file not found: {zip_path}")

    file_data = {}  # Stores raw full text content per file
    file_lines = defaultdict(list)  # Stores line-by-line content per file
    file_vars = {}  # Stores sanitized variable name to line-joined string content

    with zipfile.ZipFile(zip_path, 'r') as zipf:
        file_list = zipf.namelist()  # Get list of files in the archive
        print(f"Files in '{zip_path}':\n")

        for file_name in file_list:
            print(f"-- {file_name} --")

            # Skip directories inside zip (names ending in '/')
            if file_name.endswith('/'):
                print("(directory)\n")
                continue

            try:
                with zipf.open(file_name) as f:
                    content = f.read()  # Read file as bytes

                    try:
                        text = content.decode('utf-8')  # Decode to string

                        file_data[file_name] = text  # Save raw text
                        file_lines[file_name] = text.splitlines()  # Save list of lines

                        # Sanitize filename (remove illegal characters) for use as Python var
                        var_name = re.sub(r'[^0-9a-zA-Z_]', '_', Path(file_name).stem)
                        file_vars[var_name] = '\n'.join(file_lines[file_name])  # Join lines

                    except UnicodeDecodeError:
                        # Handle non-decodable (binary) files gracefully
                        file_data[file_name] = None
                        print("[Binary file - cannot decode]\n")
                        
            except Exception as e:
                # Handle error if file cannot be read
                print(f"[Error reading {file_name}]: {e}\n")
                file_data[file_name] = None

            print()  # Spacer after each file

    return file_data, file_lines, file_vars  # Return all collected content structures



# Example usage block
if __name__ == '__main__':
    zip_file_path = 'C://Users//jornb//Documents//GitHub//Serialpump//test ppl//Leukenaam.zip'  # Replace with your actual zip file path
    data, lines, vars_dict = read_zip_contents(zip_file_path)
    
    pump_jobs={}
    linelist= []
    for i, j in vars_dict.items():
        i = i.removesuffix("_script")
        i = i.split("_")
        i = ''.join(i)
        for line in j.split('\n'):
            line = line.strip()
            if not("*") in line and line:
                linelist.append(line)
        
        pump_jobs[i] = linelist
    
    
    x = 0
    for pump in pump_jobs:
        name = pump
        globals()[name] =  x
        x= x+1
    
    
    
    
    
    
    
    
    
    
# =============================================================================
#     
#     x=0
#     for varname, value in vars_dict.items():
#         safe_name = f"pump{x}"
#         globals()[safe_name] = value
#         print(safe_name)
#         x = x + 1
#         for line in value.split('\n'):
#             line = line.strip()
#             if not ("*") in line and line:
#                 print(line)
# =============================================================================
