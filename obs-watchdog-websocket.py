import os
import time
import subprocess
import sys
import json
import base64
import hashlib
import websocket
import threading
import socket
import configparser
from datetime import datetime

print("OBS Stream Watchdog - WebSocket Version")
print("======================================")
print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Load configuration from file
config = configparser.ConfigParser()
config_file = 'obs-watchdog-config.ini'

# Default configuration
DEFAULT_CONFIG = {
    'WebSocket': {
        'Host': 'localhost',
        'Port': '4444',
        'Password': 'fewture',
        'MaxRetries': '3',
        'RetryDelay': '5'
    },
    'Watchdog': {
        'CheckInterval': '10',
        'UseFallbackOnFailure': 'true',
        'DebugMode': 'true'
    }
}

# Check if config file exists, create it if it doesn't
if not os.path.exists(config_file):
    print(f"Configuration file {config_file} not found, creating with default values...")
    config.read_dict(DEFAULT_CONFIG)
    with open(config_file, 'w') as f:
        config.write(f)
    print(f"Created configuration file {config_file}")
else:
    print(f"Loading configuration from {config_file}...")
    config.read(config_file)

# Load configuration values
try:
    OBS_WEBSOCKET_HOST = config.get('WebSocket', 'Host')
    OBS_WEBSOCKET_PORT = config.getint('WebSocket', 'Port')
    OBS_WEBSOCKET_PASSWORD = config.get('WebSocket', 'Password')
    MAX_RETRIES = config.getint('WebSocket', 'MaxRetries')
    RETRY_DELAY = config.getint('WebSocket', 'RetryDelay')
    
    CHECK_INTERVAL = config.getint('Watchdog', 'CheckInterval')
    USE_FALLBACK_ON_FAILURE = config.getboolean('Watchdog', 'UseFallbackOnFailure')
    DEBUG_MODE = config.getboolean('Watchdog', 'DebugMode')
    
    print("Configuration loaded successfully")
except Exception as e:
    print(f"Error loading configuration: {e}")
    print("Using default values")
    
    # Default configuration values
    OBS_WEBSOCKET_HOST = 'localhost'
    OBS_WEBSOCKET_PORT = 4444
    OBS_WEBSOCKET_PASSWORD = 'fewture'
    MAX_RETRIES = 3
    RETRY_DELAY = 5
    CHECK_INTERVAL = 10
    USE_FALLBACK_ON_FAILURE = True
    DEBUG_MODE = True

# Enable WebSocket trace if in debug mode
if DEBUG_MODE:
    websocket.enableTrace(True)

# Global variables
ws = None
streaming_status = False
message_id = 1
connected = False
connection_retries = 0

def is_obs_running():
    """Check if OBS is running by looking for the process"""
    try:
        if sys.platform == "win32":
            output = subprocess.check_output("tasklist /FI \"IMAGENAME eq obs64.exe\"", shell=True)
            return b"obs64.exe" in output
        else:
            output = subprocess.check_output("ps -A | grep -i obs", shell=True)
            return b"obs" in output
    except subprocess.CalledProcessError:
        return False

def check_websocket_server():
    """Check if the WebSocket server is accessible"""
    try:
        print(f"Checking if WebSocket server is accessible at {OBS_WEBSOCKET_HOST}:{OBS_WEBSOCKET_PORT}...")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex((OBS_WEBSOCKET_HOST, OBS_WEBSOCKET_PORT))
        s.close()
        
        if result == 0:
            print("WebSocket server is accessible")
            return True
        else:
            print(f"WebSocket server is not accessible (error code: {result})")
            print("Possible reasons:")
            print("1. OBS is not running")
            print("2. WebSocket server is not enabled in OBS")
            print("3. WebSocket server is using a different port")
            print("4. Firewall is blocking the connection")
            print("5. Incorrect host/IP address")
            print("\nTo enable WebSocket in OBS:")
            print("1. Open OBS")
            print("2. Go to Tools > WebSocket Server Settings")
            print("3. Check 'Enable WebSocket server'")
            print("4. Set Server Port to match your configuration")
            print("5. Set a password if required")
            return False
    except Exception as e:
        print(f"Error checking WebSocket server: {e}")
        return False

def connect_websocket():
    """Connect to OBS WebSocket"""
    global ws, connected, connection_retries
    
    # First check if the WebSocket server is accessible
    if not check_websocket_server():
        return False
    
    try:
        # Close existing connection if any
        if ws:
            ws.close()
            
        # Create new connection
        ws_url = f"ws://{OBS_WEBSOCKET_HOST}:{OBS_WEBSOCKET_PORT}"
        print(f"Connecting to OBS WebSocket at {ws_url}...")
        print(f"Using password: {OBS_WEBSOCKET_PASSWORD != ''}")
        
        ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        
        # Start WebSocket connection in a separate thread
        wst = threading.Thread(target=ws.run_forever)
        wst.daemon = True
        wst.start()
        
        # Wait for connection to establish
        timeout = 5
        start_time = time.time()
        while not connected and time.time() - start_time < timeout:
            time.sleep(0.1)
            
        if connected:
            connection_retries = 0  # Reset retry counter on successful connection
            return True
        else:
            connection_retries += 1
            print(f"Failed to connect. Retry {connection_retries}/{MAX_RETRIES}")
            if connection_retries < MAX_RETRIES:
                print(f"Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
                return connect_websocket()  # Recursive retry
            else:
                print("Maximum retries reached. Falling back to keyboard method.")
                connection_retries = 0  # Reset for next time
                return False
    except Exception as e:
        print(f"Error connecting to WebSocket: {e}")
        connection_retries += 1
        if connection_retries < MAX_RETRIES:
            print(f"Retrying in {RETRY_DELAY} seconds... ({connection_retries}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY)
            return connect_websocket()  # Recursive retry
        else:
            print("Maximum retries reached. Falling back to keyboard method.")
            connection_retries = 0  # Reset for next time
            return False

def on_open(ws):
    """Called when WebSocket connection is established"""
    print("WebSocket connection established")
    # Authentication will be handled in on_message when we receive the hello message

def on_message(ws, message):
    """Called when a message is received from OBS WebSocket"""
    global connected, streaming_status, message_id
    
    try:
        if DEBUG_MODE:
            print(f"Raw message received: {message}")
        
        data = json.loads(message)
        
        if DEBUG_MODE:
            print(f"Received message type: {data.get('op')}")
        
        # Handle authentication
        if data.get("op") == 0:  # Hello message
            print("Received Hello message")
            
            if DEBUG_MODE:
                print(f"Full hello message: {data}")
            
            if "authentication" in data.get("d", {}):
                # Authentication required
                auth = data["d"]["authentication"]
                
                if DEBUG_MODE:
                    print(f"Authentication data: {auth}")
                
                if OBS_WEBSOCKET_PASSWORD:
                    print("Authentication required, sending credentials...")
                    # Generate authentication response
                    salt = auth["salt"]
                    challenge = auth["challenge"]
                    
                    if DEBUG_MODE:
                        print(f"Salt: {salt}")
                        print(f"Challenge: {challenge}")
                    
                    # Step 1: Concatenate password and salt
                    step1 = OBS_WEBSOCKET_PASSWORD + salt
                    
                    if DEBUG_MODE:
                        print(f"Step 1 (password+salt): {step1}")
                    
                    # Step 2: SHA256 hash and base64 encode
                    secret_hash = hashlib.sha256(step1.encode()).digest()
                    secret = base64.b64encode(secret_hash).decode()
                    
                    if DEBUG_MODE:
                        print(f"Step 2 (secret): {secret}")
                    
                    # Step 3: Concatenate secret and challenge
                    step3 = secret + challenge
                    
                    if DEBUG_MODE:
                        print(f"Step 3 (secret+challenge): {step3}")
                    
                    # Step 4: SHA256 hash and base64 encode
                    auth_response_hash = hashlib.sha256(step3.encode()).digest()
                    auth_response = base64.b64encode(auth_response_hash).decode()
                    
                    if DEBUG_MODE:
                        print(f"Step 4 (auth_response): {auth_response}")
                    
                    # Send authentication
                    auth_payload = {
                        "op": 1,
                        "d": {
                            "rpcVersion": 1,
                            "authentication": auth_response
                        }
                    }
                    
                    if DEBUG_MODE:
                        print(f"Sending authentication payload: {auth_payload}")
                    
                    ws.send(json.dumps(auth_payload))
                else:
                    print("Authentication required but no password provided")
                    ws.close()
            else:
                # No authentication required
                print("No authentication required")
                ws.send(json.dumps({
                    "op": 1,
                    "d": {
                        "rpcVersion": 1
                    }
                }))
        
        # Handle successful authentication
        elif data.get("op") == 2:  # Identified message
            print("Successfully authenticated with OBS WebSocket")
            connected = True
            # Request streaming status
            get_streaming_status()
        
        # Handle responses to our requests
        elif data.get("op") == 7:  # RequestResponse
            if "requestType" in data.get("d", {}):
                if data["d"]["requestType"] == "GetStreamStatus":
                    streaming_status = data["d"]["responseData"]["outputActive"]
                    print(f"Streaming status: {'Active' if streaming_status else 'Inactive'}")
                elif data["d"]["requestType"] == "StartStream":
                    print("Stream start command acknowledged by OBS")
                elif data["d"]["requestType"] == "StopStream":
                    print("Stream stop command acknowledged by OBS")
        
        # Handle events
        elif data.get("op") == 5:  # Event
            if "eventType" in data.get("d", {}):
                if data["d"]["eventType"] == "StreamStateChanged":
                    streaming_status = data["d"]["eventData"]["outputActive"]
                    print(f"Stream state changed: {'Active' if streaming_status else 'Inactive'}")
    
    except Exception as e:
        print(f"Error processing message: {e}")
        if DEBUG_MODE:
            import traceback
            traceback.print_exc()

def on_error(ws, error):
    """Called when a WebSocket error occurs"""
    print(f"WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    """Called when WebSocket connection is closed"""
    global connected
    connected = False
    print(f"WebSocket connection closed: {close_status_code} - {close_msg}")

def get_streaming_status():
    """Request streaming status from OBS"""
    global message_id
    
    if not connected or not ws:
        return False
    
    try:
        request = {
            "op": 6,
            "d": {
                "requestType": "GetStreamStatus",
                "requestId": str(message_id)
            }
        }
        message_id += 1
        ws.send(json.dumps(request))
        return True
    except Exception as e:
        print(f"Error requesting streaming status: {e}")
        return False

def start_streaming():
    """Start streaming in OBS via WebSocket"""
    global message_id
    
    if not connected or not ws:
        # Fall back to keyboard shortcut method
        print("WebSocket not connected, falling back to keyboard shortcut")
        start_streaming_keyboard()
        return False
    
    try:
        request = {
            "op": 6,
            "d": {
                "requestType": "StartStream",
                "requestId": str(message_id)
            }
        }
        message_id += 1
        ws.send(json.dumps(request))
        print("Start streaming request sent via WebSocket")
        return True
    except Exception as e:
        print(f"Error starting stream via WebSocket: {e}")
        # Fall back to keyboard shortcut method
        start_streaming_keyboard()
        return False

def start_streaming_keyboard():
    """Start streaming in OBS by sending Alt+F9 keyboard shortcut (fallback method)"""
    try:
        print("Attempting to start streaming via keyboard shortcut...")
        if sys.platform == "win32":
            # Create and execute a temporary VBS script to send Alt+F9
            vbs_path = os.path.join(os.environ['TEMP'], 'start_stream.vbs')
            with open(vbs_path, 'w') as f:
                f.write('Set WshShell = WScript.CreateObject("WScript.Shell")\n')
                f.write('WshShell.AppActivate "OBS"\n')
                f.write('WScript.Sleep 1000\n')
                f.write('WshShell.SendKeys "%{F9}"\n')
            
            subprocess.call(f'cscript //nologo "{vbs_path}"', shell=True)
            os.remove(vbs_path)
            print("Stream start command sent via keyboard shortcut")
        else:
            # Linux/Mac version would go here
            pass
    except Exception as e:
        print(f"Error starting stream via keyboard shortcut: {e}")

def main():
    """Main loop to monitor OBS and start streaming if needed"""
    global streaming_status, connected
    
    print("Monitoring OBS streaming status...")
    print(f"Configuration:")
    print(f"  - WebSocket Host: {OBS_WEBSOCKET_HOST}")
    print(f"  - WebSocket Port: {OBS_WEBSOCKET_PORT}")
    print(f"  - Password Set: {OBS_WEBSOCKET_PASSWORD != ''}")
    print(f"  - Check Interval: {CHECK_INTERVAL} seconds")
    print(f"  - Max Retries: {MAX_RETRIES}")
    print(f"  - Use Fallback: {USE_FALLBACK_ON_FAILURE}")
    print(f"  - Debug Mode: {DEBUG_MODE}")
    print()
    print("Press Ctrl+C to stop")
    print()
    
    while True:
        try:
            print(f"\nChecking OBS status... [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
            
            if not is_obs_running():
                print("OBS is not running. Waiting for OBS to start...")
                # Reset connection status
                if connected:
                    connected = False
                    if ws:
                        ws.close()
            else:
                print("OBS is running.")
                
                # Connect to WebSocket if not connected
                if not connected:
                    connect_websocket()
                
                # Check streaming status
                if connected:
                    # Request updated status
                    get_streaming_status()
                    time.sleep(1)  # Give time for response
                    
                    if not streaming_status:
                        print("OBS is not streaming. Starting stream...")
                        start_streaming()
                elif USE_FALLBACK_ON_FAILURE:
                    print("Not connected to OBS WebSocket. Using fallback method.")
                    # Use fallback method to start streaming
                    start_streaming_keyboard()
                else:
                    print("Not connected to OBS WebSocket and fallback is disabled.")
            
            # Wait before next check
            print(f"Checking again in {CHECK_INTERVAL} seconds...")
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            print("\nWatchdog stopped by user")
            if ws:
                ws.close()
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            if DEBUG_MODE:
                import traceback
                traceback.print_exc()
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    # Check if websocket-client is installed
    try:
        import websocket
    except ImportError:
        print("The websocket-client package is required. Installing...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "websocket-client"])
            print("websocket-client installed successfully")
            import websocket
        except Exception as e:
            print(f"Error installing websocket-client: {e}")
            print("Please install it manually with: pip install websocket-client")
            sys.exit(1)
    
    main()