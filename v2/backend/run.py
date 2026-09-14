"""
FIREX v2 Entrypoint CLI / Server Runner
"""
import uvicorn
import os
import sys

if __name__ == "__main__":
    # Ensure backend directory is on sys.path
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    
    print(f"[FIREX v2] Starting server at http://{host}:{port}/")
    print(f"[FIREX v2] API Docs: http://{host}:{port}/docs")
    print(f"[FIREX v2] Console UI: http://{host}:{port}/console/")
    print(f"[FIREX v2] Health: http://{host}:{port}/health")
    
    uvicorn.run("app.main:app", host=host, port=port, reload=True)
