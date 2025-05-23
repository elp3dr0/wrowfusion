import logging
import logging.config
import pathlib
import os
import sys

from src.db.db_init import initialise_database, DB_PATH

PROJECT_ROOT = pathlib.Path(__file__).parent.parent.absolute()

log_dir = PROJECT_ROOT / 'logs'
os.makedirs(log_dir, exist_ok=True)

loggerconfigpath = str(PROJECT_ROOT / 'config' / 'logging.conf')
logging.config.fileConfig(loggerconfigpath, disable_existing_loggers=False)
logger = logging.getLogger(__name__)

# Do not put any non-logging related imports above this line,
# especially imports from other parts of this project becuase 
# that will prevent any modules that aren't explicitly
# named in logger.conf from falling back to the default root
# logger.

import threading
import signal
from src.s4.s4 import (
    s4_heart_beat_task, 
    s4_data_task,
    RowerState 
)
from src.ble import ble_server
from src.hr.heart_rate import HeartRateMonitor
from src.ble.ble_client import HeartRateBLEScanner


def start_ws_server(hr_monitor: HeartRateMonitor, rower_state: RowerState):
    import asyncio
    import src.api.api_ws  # Your websocket server module

    asyncio.run(src.api.api_ws.ws_task(rower_state, hr_monitor))  # This runs your async server forever

# List to keep track of running threads
threads = []

def start_threads():
    """Start all necessary background tasks."""
    hr_monitor = HeartRateMonitor()
    rower_state = RowerState()

    # Thread to connect as a client to a bluetooth low energy (BLE) heart rate monitor
    # This is an object that manages its own lifecycle with asyncio so can be started using a different
    # syntax to the other threads
    ble_hrm_scanner = HeartRateBLEScanner(hr_monitor)
    ble_hrm_scanner.name = "BLEHRMScannerThread"
    threads.append(ble_hrm_scanner)
    
    # Thread for simulating heart beat to send to S4 
    # This construct is an explicit request to run a function in a separate thread (unlike ble_hrm_scanner).
    s4_heartbeat_thread = threading.Thread(target=s4_heart_beat_task, args=(hr_monitor,), daemon=True, name="S4HeatbeatThread")
    threads.append(s4_heartbeat_thread)

    # Thread for S4 polling and collating data from the S4 
    s4_data_thread = threading.Thread(target=s4_data_task, args=(rower_state,), daemon=True, name="S4DataThread")
    threads.append(s4_data_thread)

    # Thread for advertising and connecting the RPi to external Bluetooth Low Energy (BLE) clients and sending the data
    # to connected clients 
    ble_server_thread = threading.Thread(target=ble_server.ble_server_task, args=(hr_monitor, rower_state), daemon=True, name="BLEServerThread")
    threads.append(ble_server_thread)

    # Websockets server to push data to the wrowfusion dashboard (separate project)
    ws_thread = threading.Thread(target=start_ws_server, args=(hr_monitor, rower_state), daemon=True, name="WSServerThread")
    threads.append(ws_thread)

    logger.debug("wrfusion.start_threads: about to start threads")
    for thread in threads:
        thread.start()

    logger.debug("wrfusion.start_threads: creating and starting monitor_threads task")
    monitor_thread = threading.Thread(target=monitor_threads, daemon=True, name="MonitorThread")
    threads.append(monitor_thread)
    monitor_thread.start()

    # Optionally return or store monitor/scanner if needed elsewhere
    # return hr_monitor

def monitor_threads():
    """Periodically check thread health and log if any thread is not alive."""
    import time
    while True:
        for thread in threads:
            if not thread.is_alive():
                logger.warning(f"Thread {thread.name} is not alive!")
                print(f"[⚠️] Thread {thread.name} has stopped.")
            #else:
            #    print(f"[⚠️] Thread {thread.name} is alive.")
        time.sleep(10)  # Check every 10 seconds

def stop_threads(signal_received, frame):
    """Handle graceful shutdown on Ctrl+C."""
    print("\nStopping WRowFusion...")
    sys.exit(0)


def ensure_database_exists():
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        logger.warning("Workout database not found or empty. Initialising...")
        initialise_database()

if __name__ == "__main__":
    print("Starting WRowFusion...")
    
    # Handle Ctrl+C to stop gracefully
    signal.signal(signal.SIGINT, stop_threads)
    
    ensure_database_exists()
    start_threads()
    
    # Keep main thread running
    while True:
        signal.pause()