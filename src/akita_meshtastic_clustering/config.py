# Copyright (c) 2025 Akita Engineering <https://www.akitaengineering.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import os
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__) # Define logger at module level

try:
    from meshtastic.protobuf import mesh_pb2
    # Determine default port based on library availability
    DEFAULT_PORT_NUM_INT = getattr(mesh_pb2.PortNum, 'PRIVATE_APP', 4096)
except ImportError:
    logger.warning("Meshtastic protobufs not found, using default port number 4096 for DEFAULT_CONFIG.")
    DEFAULT_PORT_NUM_INT = 4096 # Fallback default port for DEFAULT_CONFIG

# Default values for configuration
DEFAULT_CONFIG = {
    "node_id": None,
    "meshtastic_port": None,
    "heartbeat_interval": 60,
    "ack_timeout": 15.0, # Use float for time values
    "rebroadcast_delay": 5.0,
    "message_retention_count": 100,     # For duplicate ID check deque
    "message_payload_retention_count": 200, # For storing payloads for sync
    "message_payload_retention_seconds": 3600.0, # Max age for stored payloads (0=disable)
    "cluster_discovery_interval": 120,
    "controller_timeout": 180.0,
    "election_timeout": 30.0,
    "sleep_interval": 300.0, # 0 to disable
    "log_level": "INFO",
    "amcs_port_num": DEFAULT_PORT_NUM_INT,
    "meshtastic_hop_limit": 3, # Default hop limit for Meshtastic sends
    "meshtastic_channel_index": 0 # Default channel index for Meshtastic sends
}

def load_config(config_path: str) -> Dict[str, Any]:
    """
    Loads configuration from a JSON file, applies defaults, and performs validation.
    """
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                user_config = json.load(f)
            # Only update keys that exist in DEFAULT_CONFIG
            valid_keys = DEFAULT_CONFIG.keys()
            filtered_user_config = {k: v for k, v in user_config.items() if k in valid_keys}
            config.update(filtered_user_config)
            logger.info(f"Loaded configuration from {config_path}")
            ignored_keys = [k for k in user_config if k not in valid_keys]
            if ignored_keys:
                logger.warning(f"Ignored unknown configuration keys: {ignored_keys}")
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from {config_path}. Using defaults.", exc_info=True)
        except Exception:
            logger.error(f"Failed to load config file {config_path}. Using defaults.", exc_info=True)
    else:
        logger.warning(f"Configuration file '{config_path}' not found. Using default values.")
        logger.warning("Ensure 'node_id' is set correctly (it cannot be defaulted).")

    # --- Validation ---
    if config.get("node_id") is None:
        raise ValueError("'node_id' is not set in the configuration.")
    if not isinstance(config.get("node_id"), int):
        raise ValueError("'node_id' must be an integer.")

    # Validate types and ranges
    for key, default_value in DEFAULT_CONFIG.items():
        if key in ["node_id", "meshtastic_port"]: continue # Handled above or allowed string

        value = config.get(key)
        if value is None and default_value is not None: # If user explicitly set to null, but we have a default
            logger.warning(f"Config key '{key}' was null, using default: {default_value}")
            config[key] = default_value
            value = default_value
        elif value is None and default_value is None: # Both null, okay
            continue

        expected_type = type(default_value)
        # Allow int where float is expected for time values
        if expected_type is float and isinstance(value, int):
            value = float(value)
            config[key] = value # Update config with corrected type

        if not isinstance(value, expected_type):
            logger.warning(f"Config key '{key}' has incorrect type (got {type(value).__name__}, expected {expected_type.__name__}). Using default: {default_value}")
            config[key] = default_value
            value = default_value

        # Range checks (ensure positive where applicable)
        if isinstance(default_value, (int, float)) and value < 0 and key not in []:
             logger.warning(f"Config key '{key}' should not be negative (got {value}). Using default: {default_value}")
             config[key] = default_value
        # Check for zero values where only specific keys allow it
        elif isinstance(default_value, (int, float)) and value == 0 and key not in ["sleep_interval", "message_payload_retention_seconds"]:
             if default_value != 0: # Only warn if default wasn't 0
                logger.warning(f"Config key '{key}' is zero (got {value}), but default is {default_value}. Check if intended. Using default.")
                config[key] = default_value

    # Validate log level string
    log_level_str = str(config.get("log_level", "INFO")).upper() # Ensure string and uppercase
    if log_level_str not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        logger.warning(f"Invalid log_level '{log_level_str}'. Using default: INFO")
        config["log_level"] = "INFO"
    else:
        config["log_level"] = log_level_str # Store the validated uppercase string

    # Validate port number range
    port_num = config.get("amcs_port_num")
    if not isinstance(port_num, int) or not (64 <= port_num <= 511): # Meshtastic user port range
        logger.warning(f"Configured amcs_port_num {port_num} is invalid or outside range (64-511). Using default: {DEFAULT_PORT_NUM_INT}")
        config["amcs_port_num"] = DEFAULT_PORT_NUM_INT

    logger.debug(f"Final configuration: {config}")
    return config

def get_log_level(log_level_str: Optional[str]) -> int:
    """Converts log level string to logging level integer."""
    return getattr(logging, str(log_level_str).upper(), logging.INFO)
