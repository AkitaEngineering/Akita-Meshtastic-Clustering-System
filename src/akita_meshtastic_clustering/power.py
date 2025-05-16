# Copyright (c) 2025 Akita Engineering <https://www.akitaengineering.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import time
import logging
from typing import Dict, Any, Optional, TYPE_CHECKING

# Setup logger for this module
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .network import MeshtasticInterface
    # Attempt import for preference setting structure - **VERIFY ACTUAL PROTOBUF STRUCTURE**
    try:
        from meshtastic.protobuf import config_pb2 # Main config
        # Specific preference groups (these are guesses, names might differ)
        DeviceConfig = getattr(config_pb2.Config, "DeviceConfig", None)
        LoRaConfig = getattr(config_pb2.Config, "LoRaConfig", None)
        BluetoothConfig = getattr(config_pb2.Config, "BluetoothConfig", None)
        PositionConfig = getattr(config_pb2.Config, "PositionConfig", None)
    except ImportError:
        logger.warning("Could not import Meshtastic protobufs for PowerManager type hints.")
        config_pb2 = None
        DeviceConfig = None # Type will be 'Any' if import fails
        LoRaConfig = None
        BluetoothConfig = None
        PositionConfig = None


# Constants for preference keys (common examples - **VERIFY THESE WITH YOUR LIBRARY/DEVICE**)
# These are typically attributes of the specific config protobuf objects.
# Example: config_pb2.Config.DeviceConfig().ls_secs
# Example: config_pb2.Config.DeviceConfig().is_router
PREF_LS_SECS = "ls_secs"                 # DeviceConfig: Light Sleep Seconds (idle time before sleep, 0=disable)
PREF_IS_ROUTER = "is_router"             # DeviceConfig: Role as a router/repeater
PREF_FIXED_POSITION = "fixed_position"   # PositionConfig: If true, GPS may sleep more
PREF_GPS_UPDATE_INTERVAL = "gps_update_interval" # PositionConfig: How often GPS updates
PREF_SEND_OWNER_INTERVAL = "send_owner_interval" # DeviceConfig? NetworkConfig? How often owner info sent (keep low?)

class PowerManager:
    """Handles logic for potential power saving. **Requires Meshtastic API verification/implementation.**"""

    def __init__(self, config: Dict[str, Any]):
        """Initializes PowerManager."""
        self.sleep_interval = config.get("sleep_interval", 300.0)
        if self.sleep_interval < 0:
            logger.warning("Negative sleep_interval in config, disabling power management.")
            self.sleep_interval = 0.0
        self.last_activity_time = time.monotonic()
        self.is_sleeping = False
        # Store original preferences to restore on wake - complex, needs careful implementation
        # self._original_prefs_on_sleep: Dict[str, Any] = {}

    def update_activity(self, activity_time: Optional[float] = None):
        """Registers node activity, potentially waking from logical sleep state."""
        now = time.monotonic()
        self.last_activity_time = activity_time if activity_time else now
        # If we were logically sleeping, trigger wake-up actions
        if self.is_sleeping:
             # This call will attempt to revert power-saving preferences
             self.force_wake_up() # Sets self.is_sleeping = False

    def check_and_manage_sleep(self, mesh_interface: Optional['MeshtasticInterface']):
        """Checks inactivity and attempts power saving via Meshtastic setPrefs API (best guess)."""
        if self.sleep_interval <= 0 or self.is_sleeping: # Disabled or already logically sleeping
            return

        time_since_activity = time.monotonic() - self.last_activity_time
        if time_since_activity >= self.sleep_interval:
            logger.info(f"Inactivity threshold reached ({time_since_activity:.1f}s). Attempting power saving via preferences.")

            # --- Meshtastic Power Saving via Preferences (Best Guess - Needs Verification) ---
            # **VERIFY**: Method ('setPrefs' or similar), preference keys/names, appropriate values,
            # and if interface.writeConfig() is needed to apply.
            try:
                if mesh_interface and mesh_interface.interface and hasattr(mesh_interface.interface, 'setNodePreference'):
                    # Some libraries use setNodePreference(pref_name_str, value)
                    # This requires knowing exact string names of preferences.

                    # Example 1: Enable light sleep by setting ls_secs to a high value
                    # (device sleeps after `ls_secs` of radio inactivity)
                    # To truly sleep based on *AMCS* inactivity, AMCS logic would drive ls_secs dynamically.
                    # Simpler: Set ls_secs to allow sleep if radio is idle for configured AMCS sleep_interval.
                    target_ls_secs = int(self.sleep_interval) # e.g., node sleeps if radio idle for this long
                    logger.info(f"Attempting to set '{PREF_LS_SECS}' to {target_ls_secs} for power saving. **VERIFY API**")
                    # mesh_interface.interface.setNodePreference(PREF_LS_SECS, target_ls_secs)
                    # self._original_prefs_on_sleep[PREF_LS_SECS] = ... # Store original value before changing

                    # Example 2: If not critical, reduce routing behavior?
                    # if self.node.role != NodeRole.CONTROLLER: # Example dependency on node state
                    #     logger.info(f"Attempting to set '{PREF_IS_ROUTER}' to False. **VERIFY API**")
                    #     # mesh_interface.interface.setNodePreference(PREF_IS_ROUTER, False)
                    #     # self._original_prefs_on_sleep[PREF_IS_ROUTER] = True # Assume was True

                    # Example 3: For fixed nodes, GPS can be less active
                    # logger.info(f"Attempting to set '{PREF_FIXED_POSITION}' to True. **VERIFY API**")
                    # mesh_interface.interface.setNodePreference(PREF_FIXED_POSITION, True)

                    # After setting preferences, they might need to be written to flash
                    # if hasattr(mesh_interface.interface, 'writeConfig'):
                    #     logger.debug("Calling interface.writeConfig() to apply power saving preferences.")
                    #     # mesh_interface.interface.writeConfig()

                    logger.warning("Executed hypothetical power saving preference changes. Effect needs full verification and API matching.")
                    self.is_sleeping = True # Mark as logically sleeping if API calls were attempted

                elif mesh_interface and mesh_interface.interface and hasattr(mesh_interface.interface, 'setPrefs'):
                     logger.warning("'setPrefs' with protobuf object needed. **This is more complex, requires knowing protobuf structure.**")
                     # Example with protobuf object (more involved):
                     # if config_pb2 and DeviceConfig:
                     #    current_config = mesh_interface.interface.radioConfig # Or .localNode.radio_config
                     #    new_device_config = DeviceConfig()
                     #    new_device_config.CopyFrom(current_config.device) # Get current settings
                     #    new_device_config.ls_secs = int(self.sleep_interval)
                     #    prefs_to_set = config_pb2.Config(device=new_device_config)
                     #    mesh_interface.interface.setPrefs(prefs_to_set)
                     #    self.is_sleeping = True
                else:
                    logger.warning("No known 'setPrefs' or 'setNodePreference' method found on interface for power management.")

            except AttributeError as ae:
                 logger.error(f"Meshtastic API Error accessing preferences: {ae}. **Verify API & Preference Keys!**")
            except meshtastic.MeshtasticError as me: # Catch specific library errors
                 logger.error(f"Meshtastic library error setting preferences: {me}")
            except Exception as e:
                 logger.error(f"Error attempting to set Meshtastic power preferences: {e}", exc_info=True)
            # --- End Meshtastic Specific Section ---


    def force_wake_up(self):
        """Force awake state. Reverts power-saving preferences set previously (best guess)."""
        if not self.is_sleeping: # Only act if logically sleeping
             return

        logger.info("Waking up / Resetting power-saving preferences to active defaults.")
        # --- Actual Meshtastic Wake Implementation (Revert Prefs) ---
        # **VERIFY**: Needs to know correct *active* values for preferences.
        # Often, setting ls_secs=0 disables light sleep, making device more active.
        try:
            if mesh_interface and mesh_interface.interface and hasattr(mesh_interface.interface, 'setNodePreference'):
                # Example: Disable light sleep for active mode
                active_ls_secs = 0 # Typically disables light sleep
                logger.info(f"Attempting to set '{PREF_LS_SECS}' to {active_ls_secs} for wake-up. **VERIFY API**")
                # mesh_interface.interface.setNodePreference(PREF_LS_SECS, active_ls_secs)

                # Example: Re-enable routing if it was disabled
                # logger.info(f"Attempting to set '{PREF_IS_ROUTER}' to True. **VERIFY API**")
                # mesh_interface.interface.setNodePreference(PREF_IS_ROUTER, True)

                # if hasattr(mesh_interface.interface, 'writeConfig'):
                #     logger.debug("Calling interface.writeConfig() to apply wake-up preferences.")
                #     # mesh_interface.interface.writeConfig()

                logger.warning("Executed hypothetical preference reset for wake-up. Effect needs verification.")
            # else if using setPrefs with protobuf:
            #   ... construct protobuf with active settings and call setPrefs ...
            else:
                logger.warning("No known 'setPrefs' or 'setNodePreference' method found for wake-up.")

        except Exception as e:
            logger.error(f"Error attempting to reset Meshtastic power preferences for wake-up: {e}", exc_info=True)
        # --- End Meshtastic Specific Section ---

        self.is_sleeping = False # Mark as logically awake
        # Update activity time to prevent immediate re-sleep
        self.last_activity_time = time.monotonic()
