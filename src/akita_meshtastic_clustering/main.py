# Copyright (c) 2025 Akita Engineering <https://www.akitaengineering.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import logging
import sys
import os
import time
import signal # For graceful shutdown
from typing import Dict, Optional, Any # For type hints

# --- Path Setup ---
# Ensures the 'src' directory is accessible for imports
try:
    # This assumes main.py is in src/akita_meshtastic_clustering/
    # Adjust if your project structure is different.
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    project_src_dir = os.path.dirname(current_file_dir) # This should be 'src/'
    # project_root_dir = os.path.dirname(project_src_dir) # This would be project root

    # Add 'src' to sys.path so 'from akita_meshtastic_clustering import ...' works
    if project_src_dir not in sys.path:
        sys.path.insert(0, project_src_dir)

    # Verify package is importable after path adjustment
    from akita_meshtastic_clustering.node import Node # Node is the main class
    from akita_meshtastic_clustering import exceptions, config as amcs_config, utils as amcs_utils
except ImportError as e:
     print(f"ERROR: Failed to import AMCS modules. Check PYTHONPATH and project structure.", file=sys.stderr)
     print(f"Current sys.path: {sys.path}", file=sys.stderr)
     print(f"Error details: {e}", file=sys.stderr)
     sys.exit(1)

# Setup initial basic logging; will be refined after config load
# This initial logger will catch issues during early config loading
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__) # Logger specific to this main script execution

# Global variable to hold the node instance for signal handling
node_instance_global: Optional[Node] = None

def handle_signal(sig, frame):
    """Gracefully handle termination signals (SIGINT, SIGTERM)."""
    signal_name = signal.Signals(sig).name
    logger.warning(f"Received signal {signal_name} ({sig}). Initiating graceful shutdown...")
    if node_instance_global:
        # Signal the node's main loop to stop by setting its _running flag
        # The node's main loop should check this flag and exit.
        # The shutdown() method will be called in the finally block of main().
        node_instance_global._running = False
        # Avoid calling shutdown directly here as it might already be in progress or
        # cause issues if called multiple times from different contexts.
        # Let the main loop's finally block handle the definitive shutdown call.
    else:
        logger.warning("Node instance not available for signal handler cleanup. Exiting directly.")
        sys.exit(1) # Exit if node instance isn't set, as nothing to shut down gracefully


def main():
    """Main entry point for running an AMCS Node."""
    global node_instance_global # Allow main to set the global instance

    parser = argparse.ArgumentParser(
        description="Run an Akita Meshtastic Clustering System (AMCS) Node.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--config",
        type=str,
        default="cluster_config.json", # Assumes config is in the CWD where script is run
        help="Path to the AMCS node configuration JSON file.",
    )
    # Add more CLI arguments here if needed (e.g., for sending a test message once)
    args = parser.parse_args()

    config_path = args.config

    # Configure logging properly based on config file (or defaults if file error)
    log_level_from_config = logging.INFO # Default if config load fails
    try:
        # load_config handles defaults and validation, may raise ConfigurationError
        loaded_config = amcs_config.load_config(config_path)
        log_level_from_config = amcs_config.get_log_level(loaded_config.get('log_level'))
    except exceptions.ConfigurationError as e:
         # Critical config error (e.g., missing node_id), already logged by load_config.
         logger.critical(f"Halting due to critical configuration error from '{config_path}': {e}")
         sys.exit(1) # Exit if config is fundamentally broken
    except Exception as e:
         # Non-critical config load errors were logged by load_config
         logger.warning(f"Using default INFO logging level due to error reading config '{config_path}': {e}")
         pass # Continue with default log level if less critical error

    amcs_utils.setup_logging(level=log_level_from_config) # Reconfigure with correct level
    logger.info(f"AMCS Node starting. Effective logging level: {logging.getLevelName(log_level_from_config)}")
    logger.info(f"Using configuration file: {os.path.abspath(config_path)}")


    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, handle_signal)  # Handle Ctrl+C
    signal.signal(signal.SIGTERM, handle_signal) # Handle kill/system shutdown (e.g., systemd)

    # --- Node Initialization and Startup ---
    current_node_instance = None # Local var for clarity in try/finally
    try:
        # --- Define your application callbacks here ---
        def my_app_data_handler(app_payload: Dict[str, Any]):
            """Example callback for received application data."""
            logger.info(f"--- My Application: Received Data ---")
            logger.info(f"Data Payload: {app_payload}")
            # Add your application-specific processing logic here
            # e.g., store to database, update UI, trigger other actions

        def my_send_failure_handler(msg_id: str, destination: str, original_msg_payload: Dict[str, Any]):
            """Example callback for permanent send failures."""
            logger.error(f"--- My Application: Notified Send Failure ---")
            logger.error(f"Failed to deliver AMCS message ID {msg_id[-8:]} to destination {destination}.")
            logger.error(f"Original message type: {original_msg_payload.get('type')}, Content: {original_msg_payload.get('p')}")
            # Add app logic: e.g., log to persistent failure queue, alert user, try alternative comms?

        # Pass config path and callbacks to the Node constructor
        current_node_instance = Node(
            config_path=config_path,
            application_callback=my_app_data_handler,
            on_send_failure_callback=my_send_failure_handler
        )
        node_instance_global = current_node_instance # Store globally for signal handler

        current_node_instance.run() # This blocks until node shuts down or critical error

    except exceptions.AMCSException as e: # Catch specific AMCS setup errors
        logger.critical(f"CRITICAL AMCS ERROR during node setup or runtime: {e}", exc_info=True)
        sys.exit(1)
    except RuntimeError as e: # Catch runtime errors from Node init
         logger.critical(f"CRITICAL RUNTIME ERROR during node initialization: {e}", exc_info=True)
         sys.exit(1)
    except Exception as e: # Catch any other unexpected critical errors
        logger.critical(f"UNEXPECTED CRITICAL ERROR during node execution: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # This block executes on normal exit, Ctrl+C, or unhandled exception in run()
        logger.info("Main execution context finishing or interrupted.")
        if node_instance_global: # Use the global instance that signal handler sees
             if node_instance_global._running: # If loop exited but _running still true (e.g. unhandled exception)
                  logger.warning("Node loop exited unexpectedly but _running flag was still set. Forcing shutdown.")
             node_instance_global.shutdown() # Ensure cleanup, safe to call multiple times if needed
        else:
             logger.info("No active node instance to shut down.")

        logger.info("AMCS Node process fully exited.")

if __name__ == "__main__":
    main()
