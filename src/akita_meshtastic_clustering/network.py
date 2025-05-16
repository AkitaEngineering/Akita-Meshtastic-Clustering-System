# Copyright (c) 2025 Akita Engineering <https://www.akitaengineering.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import meshtastic
import meshtastic.serial_interface
import meshtastic.tcp_interface
from pubsub import pub

# Setup logger for this module
logger = logging.getLogger(__name__)

try:
    # Attempt to import common protobufs for type hints and constants
    from meshtastic.protobuf import mesh_pb2, channel_pb2, config_pb2
    # Determine broadcast address constant safely
    BROADCAST_NUM = getattr(mesh_pb2, 'BROADCAST_NUM', 0xFFFFFFFF)
    # Define PortNum type if available, otherwise use int
    # Using PRIVATE_APP as default if specific number not configured well
    DEFAULT_PORT_NUM_INT_FOR_NET = getattr(mesh_pb2.PortNum, 'PRIVATE_APP', 4096) # Different name to avoid conflict with config.py
    PortNum = getattr(mesh_pb2, 'PortNum', int)
except ImportError:
    logger.warning("Could not import Meshtastic protobufs. Using defaults/integers for NetworkInterface.")
    mesh_pb2 = None
    config_pb2 = None
    BROADCAST_NUM = 0xFFFFFFFF
    DEFAULT_PORT_NUM_INT_FOR_NET = 4096 # Fallback default port
    PortNum = int # Fallback type

from typing import Optional, Callable, Any, Dict, Union
import logging # Already imported, but good for clarity
import time
import json
import threading

from .exceptions import NetworkError

# Constants
CONNECTION_RETRY_DELAY = 5.0 # seconds
NODE_INFO_FETCH_DELAY = 1.0  # seconds
NODE_INFO_FETCH_RETRIES = 5

class MeshtasticInterface:
    """
    Wraps Meshtastic communication. **API Calls Must Be Verified!**

    Handles device connection (Serial/TCP), message sending, receiving via PubSub,
    and provides callbacks. Assumes meshtastic-python v2.x API conventions.
    """
    MeshInterfaceType = Union[meshtastic.serial_interface.SerialInterface, meshtastic.tcp_interface.TCPInterface]

    def __init__(self, config: Dict[str, Any], on_receive_callback: Optional[Callable[[Dict], None]] = None, on_connection_callback: Optional[Callable[[Dict], None]] = None):
        """Initializes the MeshtasticInterface."""
        self.config = config
        self.device_port: Optional[str] = config.get('meshtastic_port')
        # Ensure port number is valid type for the library
        try:
             # Validate configured port number against allowed range
             conf_port_num = int(config.get('amcs_port_num', DEFAULT_PORT_NUM_INT_FOR_NET))
             if not (64 <= conf_port_num <= 511): # Check Meshtastic valid user range
                  logger.warning(f"Configured amcs_port_num {conf_port_num} outside valid range (64-511). Using default: {DEFAULT_PORT_NUM_INT_FOR_NET}")
                  conf_port_num = DEFAULT_PORT_NUM_INT_FOR_NET
             # Cast to PortNum enum type if protobufs available, otherwise keep as int
             self.amcs_port_num: PortNum = PortNum(conf_port_num)
        except (ValueError, TypeError) as e:
             logger.error(f"Invalid amcs_port_num in config, using default {DEFAULT_PORT_NUM_INT_FOR_NET}. Error: {e}")
             self.amcs_port_num = PortNum(DEFAULT_PORT_NUM_INT_FOR_NET)

        self._on_receive_callback = on_receive_callback
        self._on_connection_callback = on_connection_callback
        self.interface: Optional[MeshtasticInterface.MeshInterfaceType] = None
        self._is_connected = False
        self._node_info: Optional[Dict] = None
        self._connection_lock = threading.Lock()
        logger.info(f"Meshtastic Interface configured for AMCS PortNum: {self.amcs_port_num} (Value: {int(self.amcs_port_num)})")


    def connect(self):
        """Establishes connection to the Meshtastic device in a separate thread."""
        if self.is_connected or self._connection_lock.locked(): # Check lock too
             logger.debug("Connect called but already connected or connecting.")
             return
        if not self._connection_lock.acquire(blocking=False):
            logger.warning("Connection attempt already in progress.")
            return

        logger.info("Starting connection worker thread...")
        thread = threading.Thread(target=self._connect_worker, name="MeshtasticConnectThread", daemon=True)
        thread.start()


    def _connect_worker(self):
        """Worker thread function to handle connection attempts and setup."""
        attempt = 0
        max_attempts = 3 # Limit connection retries
        try:
            while not self._is_connected and attempt < max_attempts: # Use internal flag
                attempt += 1
                logger.info(f"Connecting to Meshtastic device... (Attempt {attempt}/{max_attempts})")
                try:
                    # --- API Call: Interface Initialization ---
                    # **VERIFY** constructor arguments for your version (e.g., noUnexpected=True?)
                    if self.device_port:
                        if ":" in self.device_port: # TCP Check
                            hostname, port_str = self.device_port.split(":", 1)
                            port = int(port_str) if port_str else 4403
                            logger.info(f"Attempting TCP connection to {hostname}:{port}")
                            self.interface = meshtastic.tcp_interface.TCPInterface(hostname=hostname, port=port)
                        else: # Serial
                            logger.info(f"Attempting Serial connection to {self.device_port}")
                            # Example: SerialInterface(devPath=self.device_port, noProto=False, connectAttemptTimeout=10)
                            self.interface = meshtastic.serial_interface.SerialInterface(devPath=self.device_port)
                    else: # Serial Auto-Detect
                        logger.info("Attempting Serial auto-detect connection")
                        self.interface = meshtastic.serial_interface.SerialInterface()

                    # If constructor succeeded, library often connects automatically or provides method.
                    # Some interfaces might require interface.connect() or interface.start()
                    # For now, assume constructor implies connection attempt.
                    # _is_connected will be set by _internal_on_connection or _fetch_node_info success.

                    logger.info("Meshtastic link established. Fetching node info...")
                    self._fetch_node_info(retries=NODE_INFO_FETCH_RETRIES)
                    if not self._node_info:
                         logger.warning("Continuing without initial node info after connection attempt.")
                         # This might be okay if node info is eventually populated by events.

                    # --- API Call: PubSub Subscription ---
                    logger.debug("Subscribing to Meshtastic PubSub events.")
                    try:
                        # **VERIFY THESE TOPIC NAMES**
                        pub.subscribe(self._internal_on_receive, "meshtastic.receive.data")
                        pub.subscribe(self._internal_on_connection, "meshtastic.connection.established")
                        pub.subscribe(self._internal_on_connection, "meshtastic.connection.lost")
                        pub.subscribe(self._internal_on_connection, "meshtastic.connection.closed")
                    except Exception as pubsub_err:
                        logger.critical(f"Failed to subscribe to Meshtastic PubSub events: {pubsub_err}. Critical functionality failure.", exc_info=True)
                        if self.interface: self.interface.close() # Clean up
                        self.interface = None; self._is_connected = False
                        raise NetworkError(f"PubSub subscription failed: {pubsub_err}")

                    # Manually trigger connection callback after successful setup (if not done by event)
                    # State will be confirmed by events or next check of interface.isConnected()
                    # self._internal_on_connection(topic_name_override="meshtastic.connection.established") # Reconsider manual trigger
                    logger.info("Meshtastic interface listeners attached.")
                    break # Exit retry loop on apparent success of init and subscribe

                except meshtastic.MeshtasticError as e:
                    logger.error(f"Meshtastic connection error (Attempt {attempt}): {e}")
                    self._is_connected = False; self.interface = None; self._node_info = None
                    if attempt < max_attempts: time.sleep(CONNECTION_RETRY_DELAY)
                    else: raise NetworkError(f"Meshtastic connection failed after {max_attempts} attempts: {e}")
                except Exception as e:
                    logger.error(f"Unexpected connection error (Attempt {attempt}): {e}", exc_info=True)
                    self._is_connected = False; self.interface = None; self._node_info = None
                    if attempt < max_attempts: time.sleep(CONNECTION_RETRY_DELAY)
                    else: raise NetworkError(f"Unexpected connection error after {max_attempts} attempts: {e}")
        finally:
             if self._connection_lock.locked():
                 self._connection_lock.release()


    def _fetch_node_info(self, retries=NODE_INFO_FETCH_RETRIES, delay=NODE_INFO_FETCH_DELAY):
        """Attempts to retrieve and store the local node information."""
        if not self.interface:
            logger.warning("Cannot fetch node info, interface not available.")
            self._node_info = None
            return

        logger.debug(f"Attempting to fetch node info ({retries} retries)...")
        for attempt in range(retries):
            try:
                # --- API Call: Node Info Access ---
                # **VERIFY**: myInfo, nodes attributes and their structure. interface.localNode can be better.
                # Example: Use interface.getNode('^local') to get current node details.
                # info = self.interface.myInfo # May be stale or basic
                # nodes_db = self.interface.nodes
                local_node_obj = self.interface.getNode('^local', updateIfStale=True) # Force update

                if local_node_obj and hasattr(local_node_obj, 'num') and local_node_obj.num is not None:
                    my_num = local_node_obj.num
                    # Extract details safely using getattr with defaults
                    hw_model = getattr(local_node_obj, 'hwModelStr', 'N/A') # Check attribute name
                    firmware = getattr(local_node_obj, 'firmwareVersion', 'N/A')
                    mac_addr = getattr(local_node_obj, 'macaddr', 'N/A')
                    user = getattr(local_node_obj, 'user', None)
                    long_name = getattr(user, 'longName', 'N/A') if user else 'N/A'

                    self._node_info = {
                        "node_id_hex": f"!{my_num:x}",
                        "node_id_int": my_num,
                        "long_name": long_name,
                        "hw_model": hw_model,
                        "firmware": firmware,
                        "mac_addr": mac_addr,
                        "reboot_count": getattr(self.interface.myInfo, 'reboot_count', 'N/A') if self.interface.myInfo else 'N/A'
                    }
                    logger.info(f"Successfully retrieved node info: {self._node_info}")
                    self._is_connected = True # Confirm connected if node info is fetched
                    return # Success
                else:
                     logger.debug(f"Node info partial/missing (Attempt {attempt+1}/{retries}). NodeObj: {local_node_obj}")

            except AttributeError as ae:
                 logger.error(f"API Error fetching node info (Attempt {attempt+1}/{retries}): Attribute missing {ae}. **Verify API!**")
            except meshtastic.MeshtasticError as me: # Library might raise specific errors
                 logger.warning(f"Meshtastic library error fetching node info (Attempt {attempt+1}/{retries}): {me}")
            except Exception as e:
                 logger.warning(f"Error during node info fetch (Attempt {attempt+1}/{retries}): {e}", exc_info=True)

            if attempt < retries - 1: time.sleep(delay)
        logger.error(f"Failed to retrieve valid node info after {retries} attempts. Interface might not be fully ready.")
        self._node_info = None
        self._is_connected = False # If node info critical and failed, mark as not connected


    def _internal_on_receive(self, packet, interface=None): # interface arg often passed by PubSub
        """ PubSub callback for 'meshtastic.receive.data'. **Verify packet structure.** """
        try:
            if not isinstance(packet, dict):
                 logger.warning(f"Received non-dict packet: {type(packet)}")
                 return

            # --- API Assumption: Packet Structure & Filtering ---
            from_node_id_int = packet.get('from')
            to_node_id_int = packet.get('to') # For filtering
            decoded_payload = packet.get("decoded")

            my_node_num = self._node_info.get('node_id_int') if self._node_info else None
            if my_node_num is None:
                 logger.warning("Cannot process received packet: Own node ID unknown.")
                 return

            if not (to_node_id_int == my_node_num or to_node_id_int == BROADCAST_NUM):
                 return # Not for us

            if not isinstance(decoded_payload, dict) or from_node_id_int is None:
                logger.debug(f"Received packet missing 'decoded' dict or 'from' field. Packet: {packet}")
                return

            # --- API Assumption: Decoded Payload Keys & PortNum Filtering ---
            portnum_val = decoded_payload.get("portnum")
            payload_bytes = decoded_payload.get('payload') # Should be bytes

            if portnum_val is not None and PortNum(portnum_val) == self.amcs_port_num and isinstance(payload_bytes, bytes):
                from_node_id_hex = f"!{from_node_id_int:x}"
                logger.debug(f"Received AMCS Data: From={from_node_id_hex}, To={to_node_id_int:x}, Port={int(self.amcs_port_num)}, RSSI={packet.get('rxRssi')}, SNR={packet.get('rxSnr')}")

                try:
                    payload_str = payload_bytes.decode('utf-8')
                    payload_dict = json.loads(payload_str)

                    received_data = {
                        'from_id_int': from_node_id_int,
                        'from_id_hex': from_node_id_hex,
                        'to_id_int': to_node_id_int,
                        'payload': payload_dict,
                        'rssi': packet.get('rxRssi'),
                        'snr': packet.get('rxSnr'),
                        'hop_limit': decoded_payload.get('hopLimit'),
                        'received_at': time.time()
                    }

                    if self._on_receive_callback:
                        self._on_receive_callback(received_data)

                except (UnicodeDecodeError, json.JSONDecodeError) as decode_err:
                    logger.warning(f"Could not decode AMCS JSON payload from {from_node_id_hex}. Error: {decode_err}. Payload: {payload_bytes!r}")
                except Exception as proc_err:
                    logger.exception(f"Error processing decoded AMCS packet from {from_node_id_hex}")
            # else: Ignoring packet on different port or non-bytes payload
        except Exception as e:
            logger.exception(f"Critical error in _internal_on_receive. Raw packet: {packet}")


    def _internal_on_connection(self, interface=None, topic=pub.AUTO_TOPIC, topic_name_override=None):
        """ PubSub callback for 'meshtastic.connection.*'. Handles status changes. """
        try:
            topic_name = topic_name_override if topic_name_override else topic.getName()
            logger.debug(f"Connection event: {topic_name}")

            new_status_str = "unknown"
            new_is_connected = self._is_connected # Assume no change initially
            current_node_info = self._node_info

            if topic_name.endswith("established"):
                new_status_str = "connected"
                new_is_connected = True
                if not self._node_info: # If info was missing, try fetching it now
                    logger.info("Connection established, attempting to fetch node info.")
                    self._fetch_node_info(retries=3)
                current_node_info = self._node_info # Use potentially updated info
            elif topic_name.endswith("lost") or topic_name.endswith("closed"):
                new_status_str = "disconnected"
                new_is_connected = False
                current_node_info = None # Clear node info on disconnect
            else:
                logger.warning(f"Unhandled connection topic: {topic_name}, re-assessing link status.")
                # Fallback: directly check interface if topic is ambiguous
                current_conn_state_direct = False
                if self.interface and hasattr(self.interface, 'isConnected'):
                     try: current_conn_state_direct = self.interface.isConnected()
                     except: pass
                new_is_connected = current_conn_state_direct
                new_status_str = "connected" if new_is_connected else "disconnected"

            # Update state and callback only if status actually changed
            if self._is_connected != new_is_connected or (new_is_connected and not self._node_info): # Report if became connected or info updated
                self._is_connected = new_is_connected
                self._node_info = current_node_info # Update cached node_info
                logger.info(f"Meshtastic connection status update: {new_status_str}")
                if self._on_connection_callback:
                    self._on_connection_callback({ "status": new_status_str, "node_info": self._node_info })
        except Exception as e:
            logger.exception("Critical error in _internal_on_connection callback")


    def send_message(self, payload_dict: Dict, destination_id_hex: str = "!ffffffff"):
        """Sends an AMCS message via Meshtastic interface.sendData."""
        if not self.is_connected or not self.interface:
            raise NetworkError("Not connected to Meshtastic device for sending")

        try:
            payload_str = json.dumps(payload_dict, separators=(',', ':'))
            payload_bytes = payload_str.encode('utf-8')

            if len(payload_bytes) > 230: # Common LoRa payload limit
                 logger.warning(f"Message size ({len(payload_bytes)} bytes) may exceed typical LoRa limit.")

            # Get hopLimit and channelIndex from config, with defaults
            hop_limit = self.config.get("meshtastic_hop_limit", 3)
            channel_index = self.config.get("meshtastic_channel_index", 0)

            logger.debug(f"Attempting sendData: Dest={destination_id_hex}, Port={int(self.amcs_port_num)}, "
                         f"Size={len(payload_bytes)}, HopLimit={hop_limit}, Chan={channel_index}")
            try:
                # --- API Call: sendData ---
                # **VERIFY**: Method signature, parameter names, and types.
                self.interface.sendData(
                    payload_bytes,
                    destinationId=destination_id_hex,
                    portNum=self.amcs_port_num, # Must match expected type (int or PortNum enum)
                    wantAck=False, # AMCS handles its own application-level ACKs
                    hopLimit=hop_limit,
                    channelIndex=channel_index
                )
                logger.debug(f"Meshtastic sendData call appears successful (message queued).")
            except AttributeError as ae:
                 logger.critical(f"Meshtastic API Error: interface.sendData method missing or incorrect. **Verify API!** {ae}")
                 raise NetworkError(f"Meshtastic API mismatch: sendData failed.")
            except meshtastic.MeshtasticError as me:
                 logger.error(f"Meshtastic library error during sendData: {me}")
                 raise NetworkError(f"Meshtastic send failed: {me}")
            except Exception as api_err:
                 logger.exception(f"Unexpected error during interface.sendData call")
                 raise NetworkError(f"Meshtastic API send error: {api_err}")

        except Exception as e:
            logger.exception(f"Error preparing message for sending")
            raise NetworkError(f"Unexpected send preparation error: {e}")


    def get_node_info(self) -> Optional[Dict]:
        """Gets locally cached information about the connected Meshtastic node."""
        return self._node_info

    @property
    def is_connected(self) -> bool:
        """Returns the current assessed connection status."""
        return self._is_connected

    def close(self):
        """Closes the connection and unsubscribes from PubSub."""
        if self.interface:
            logger.info("Closing Meshtastic interface...")
            # Unsubscribe listeners first to prevent callbacks on closed interface
            try:
                logger.debug("Unsubscribing from Meshtastic PubSub events.")
                # **VERIFY** Topic names match those used in connect.
                pub.unsubscribe(self._internal_on_receive, "meshtastic.receive.data")
                pub.unsubscribe(self._internal_on_connection, "meshtastic.connection.established")
                pub.unsubscribe(self._internal_on_connection, "meshtastic.connection.lost")
                pub.unsubscribe(self._internal_on_connection, "meshtastic.connection.closed")
            except Exception as pubsub_err:
                 logger.error(f"Error unsubscribing from PubSub during close: {pubsub_err}", exc_info=True)

            # Close the interface connection
            try:
                # --- API Call: close() ---
                logger.debug("Calling interface.close()")
                self.interface.close()
            except AttributeError as ae:
                 logger.error(f"Meshtastic API Error: interface.close method missing. **Verify API!** {ae}")
            except Exception as e:
                 logger.error(f"Error during Meshtastic interface.close(): {e}", exc_info=True)
            finally:
                 # Ensure state is updated regardless of close errors
                 self.interface = None
                 self._is_connected = False
                 self._node_info = None
                 logger.info("Meshtastic interface closed and state reset.")
        else:
             logger.debug("Close called but interface not active.")
