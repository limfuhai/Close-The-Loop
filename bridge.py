#!/usr/bin/env python3
"""
Boundary Bridge - Connects your local machine to Boundary's AI
Version: 1.0.0

This lightweight script enables Boundary to access your local files and execute
commands on your machine. All data stays local - only commands and results
are sent to Boundary's servers via secure HTTPS.

NO EXTERNAL DEPENDENCIES - Uses only Python standard library.
"""

import urllib.request
import urllib.parse
import urllib.error
import subprocess
import time
import json
import sys
import os
from pathlib import Path

class BoundaryBridge:
    def __init__(self):
        # IMPORTANT: This token is unique to your account
        # Keep it secret - it grants access to your Boundary account
        self.api_key = "{{BOUNDARY_API_KEY}}"  # Will be replaced with actual key
        
        # Boundary API endpoint
        self.api_base = "http://localhost:8770"
        
        # Connection state
        self.connected = False
        self.poll_interval = 2  # seconds
        
    def _make_request(self, endpoint, method="POST", data=None):
        """Make HTTP request using urllib (no external dependencies)"""
        url = f"{self.api_base}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Prepare request data
        if data:
            data = json.dumps(data).encode('utf-8')
        
        # Create request
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method
        )
        
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                response_data = response.read().decode('utf-8')
                return json.loads(response_data) if response_data else {}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return {"error": "Invalid API key", "status_code": 401}
            elif e.code == 404:
                return {"error": "Endpoint not found", "status_code": 404}
            else:
                return {"error": f"HTTP {e.code}: {e.reason}", "status_code": e.code}
        except urllib.error.URLError as e:
            return {"error": f"Connection failed: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}
    
    def validate_token(self):
        """Verify that the API key is valid"""
        try:
            result = self._make_request("/api/bridge/verify", method="POST")
            
            if result.get("status_code") == 401:
                print(f"❌ Invalid API key")
                return False
            elif "error" in result:
                print(f"❌ Connection error: {result['error']}")
                return False
            else:
                return True
                
        except Exception as e:
            print(f"❌ Validation error: {e}")
            return False
    
    def poll_for_commands(self):
        """Poll server for pending commands"""
        try:
            result = self._make_request("/api/bridge/poll", method="POST")
            
            if "error" in result:
                # Silently ignore poll errors (normal during connection issues)
                return None
            
            if result.get("has_commands"):
                return result.get("commands", [])
            
            return None
            
        except Exception:
            # Silently ignore exceptions during polling
            return None
    
    def execute_command(self, command):
        """Execute command locally and return results"""
        cmd_type = command.get("type", "bash")
        cmd_text = command.get("cmd", "")
        
        print(f"📝 Executing: {cmd_text}")
        
        try:
            if cmd_type == "bash":
                result = subprocess.run(
                    cmd_text,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                return {
                    "output": result.stdout,
                    "error": result.stderr,
                    "status": result.returncode,
                    "success": result.returncode == 0
                }
            
            elif cmd_type == "python":
                # Execute Python code
                result = subprocess.run(
                    [sys.executable, "-c", cmd_text],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                return {
                    "output": result.stdout,
                    "error": result.stderr,
                    "status": result.returncode,
                    "success": result.returncode == 0
                }
                
        except subprocess.TimeoutExpired:
            return {
                "error": "Command timed out (30 seconds)",
                "status": -1,
                "success": False
            }
        except Exception as e:
            return {
                "error": str(e),
                "status": -1,
                "success": False
            }
    
    def send_results(self, command_id, results):
        """Send command results back to server"""
        try:
            data = {
                "command_id": command_id,
                "results": results
            }
            
            result = self._make_request("/api/bridge/results", method="POST", data=data)
            
            if "error" not in result:
                print(f"✓ Results sent")
            else:
                print(f"⚠️  Failed to send results")
                
        except Exception as e:
            print(f"⚠️  Error sending results: {e}")
    
    def run(self):
        """Main polling loop - runs forever"""
        print("\n" + "="*60)
        print("🌊 Boundary Bridge v1.0.0")
        print("="*60)
        print()
        
        # Check if token is placeholder
        if self.api_key.startswith("{{BOUNDARY"):
            print("❌ Error: API key not configured")
            print()
            print("This file needs to be downloaded from boundary.xuanwo.ai")
            print("with your personal API key embedded.")
            print()
            print("Please visit https://boundary.xuanwo.ai and download")
            print("the bridge file from your dashboard.")
            print()
            sys.exit(1)
        
        # Validate token
        print("🔐 Validating API key...")
        if not self.validate_token():
            print()
            print("Please check your API key or download a new bridge file")
            print("from https://boundary.xuanwo.ai")
            print()
            sys.exit(1)
        
        print("✓ API key validated")
        print()
        print("🔗 Bridge connected to Boundary")
        print("📍 Polling server every 2 seconds...")
        print()
        print("💡 Keep this terminal window open")
        print("💡 You can now use boundary.xuanwo.ai normally")
        print("💡 Press Ctrl+C to stop the bridge")
        print()
        print("="*60)
        print()
        
        self.connected = True
        
        # Infinite polling loop
        try:
            while True:
                commands = self.poll_for_commands()
                
                if commands:
                    for cmd in commands:
                        cmd_id = cmd.get("id")
                        
                        # Execute command
                        results = self.execute_command(cmd)
                        
                        # Show result preview
                        if results.get("success"):
                            output = results.get("output", "")
                            preview = output[:100] + "..." if len(output) > 100 else output
                            # print(f"✓ Result: {preview}")
                        else:
                            error = results.get("error", "Unknown error")
                            print(f"❌ Error: {error}")
                        
                        # Send results back
                        self.send_results(cmd_id, results)
                        print()
                
                time.sleep(self.poll_interval)
                
        except KeyboardInterrupt:
            print()
            print("="*60)
            print("🛑 Bridge stopped by user")
            print("="*60)
            print()
            sys.exit(0)

if __name__ == "__main__":
    bridge = BoundaryBridge()
    bridge.run()