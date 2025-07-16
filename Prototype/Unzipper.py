# file: read_zip_files.py
import zipfile  # Module for handling zip archives
from pathlib import Path  # Provides object-oriented file system paths
from collections import defaultdict  # For storing structured line data
import re  # For sanitizing variable names

def read_zip_contents(zip_path):
    """
    Reads file contents from a zip archive and stores them in memory.

    Parameters:
    zip_path (str or Path): Path to the zip file

    Returns:
    tuple: (file_data, file_lines, file_vars)
        file_data (dict): Maps file names to full text content
        file_lines (dict): Maps file names to list of lines
        file_vars (dict): Maps sanitized file names to joined line strings

    Raises:
    FileNotFoundError: If the zip file does not exist at the specified path
    """
    if not Path(zip_path).is_file():
        raise FileNotFoundError(f"Zip file not found: {zip_path}")

    file_data = {}  # Maps file names to their entire text content
    file_lines = defaultdict(list)  # Maps file names to lists of lines
    file_vars = {}  # Maps sanitized file names to text content

    with zipfile.ZipFile(zip_path, 'r') as zipf:
        file_list = zipf.namelist()
        print(f"Files in '{zip_path}':\n")

        for file_name in file_list:
            print(f"-- {file_name} --")

            if file_name.endswith('/'):
                print("(directory)\n")
                continue

            try:
                with zipf.open(file_name) as f:
                    content = f.read()
                    try:
                        text = content.decode('utf-8')
                        file_data[file_name] = text
                        file_lines[file_name] = text.splitlines()

                        # Sanitize filename to valid variable name
                        var_name = re.sub(r'[^0-9a-zA-Z_]', '_', Path(file_name).stem)
                        file_vars[var_name] = '\n'.join(file_lines[file_name])

                        print(text)
                    except UnicodeDecodeError:
                        file_data[file_name] = None
                        print("[Binary file - cannot decode]\n")
            except Exception as e:
                print(f"[Error reading {file_name}]: {e}\n")
                file_data[file_name] = None

            print()

    return file_data, file_lines, file_vars


# Example usage block
if __name__ == '__main__':
    zip_file_path = 'C://Users//jornb//Documents//GitHub//Serialpump//test ppl//Leukenaam.zip'  # Replace with your actual zip file path
    data, lines, vars_dict = read_zip_contents(zip_file_path)
    
    
    
    
    # Example inspection
    print("\n--- Summary ---")
    for varname, text in vars_dict.items():
        print(f"{varname} =\n{text}\n")