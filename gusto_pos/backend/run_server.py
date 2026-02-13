import os
import sys
import subprocess

# Set up PYTHONPATH
backend_dir = os.path.dirname(os.path.abspath(__file__))
os.environ['PYTHONPATH'] = backend_dir
sys.path.insert(0, backend_dir)

# Change to backend directory
os.chdir(backend_dir)

# Run uvicorn
print(f"Starting Gusto POS Backend...")
print(f"Working Directory: {os.getcwd()}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH')}")

# Run uvicorn directly
subprocess.run([
    sys.executable, '-m', 'uvicorn',
    'app.main:app',
    '--reload',
    '--host', '0.0.0.0',
    '--port', '8000'
])
