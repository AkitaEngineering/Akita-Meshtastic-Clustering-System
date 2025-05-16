# Copyright (c) 2025 Akita Engineering <https://www.akitaengineering.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import time
import logging
from enum import Enum, auto
import sys
from typing import Dict, Any, Optional, Set, TYPE_CHECKING, Callable, Tuple
import threading
import random
from collections import defaultdict

from .config import load_config, get_log_level # Ensure get_log_level is imported
from .network import MeshtasticInterface
from .messaging import MessageHandler
from .cluster import ClusterManager
from .controller import ControllerLogic
from .power import PowerManager
from .utils import Timer, setup_logging # Removed get_log_level, use from config module
from .exceptions import ConfigurationError, NetworkError, StateError, MessageError
from .messaging import (MSG_TYPE_APP_DATA, MSG_TYPE_ACK, MSG_TYPE_HEARTBEAT,
                        MSG_TYPE_DISCOVERY_REQ, MSG_TYPE_DISCOVERY_RESP,
                        MSG_TYPE_ELECTION_REQUEST, MSG_TYPE_ELECTION_VOTE, MSG_TYPE_ELECTION_WINNER,
                        MSG_TYPE_SYNC_INFO, MSG_TYPE_SYNC_REQ,
                        MSG_TYPE_MISSING_MSG_REQ, MSG_TYPE_MISSING_MSG_RESP)

# Conditional import for type checking
if TYPE_CHECKING:
    from meshtastic import MeshInterface # For type hinting

logger = logging.getLogger(__name__)

# Define Node Roles
class NodeRole(Enum):
    """Defines the possible operational roles for a node."""
    INITIALIZING = auto()
    DISCOVERING = auto()
    ELECTION = auto()
    MEMBER = auto()
    CONTROLLER = auto()

# Constants
MAX_ACK_RETRIES = 3
BASE_ACK_BACKOFF_DELAY = 0.5  # seconds
MAX_SEND_ATTEMPTS = 3
SEND_RETRY_DELAY = 0.2 # seconds
STATS_LOG_INTERVAL_DEFAULT = 300.0 # Log stats every 5 minutes

class Node:
    """
    Represents a single node in the Akita Meshtastic Clustering System network.
    Manages state, role transitions, network interaction, message handling, and components.
    """

    def __init__(self,
                 config_path: str,
                 application_callback: Optional[Callable[[Dict], None]] = None,
                 on_send_failure_callback: Optional[Callable[[str, str, Dict], None]] = None):
        """
        Initializes the AMCS Node.
        Args:
            config_path: Path to the configuration file.
            application_callback: Called when application data is received. Accepts payload dict.
            on_send_failure_callback: Called when sending a direct message permanently fails.
                                      Accepts (message_id, destination_id_hex, original_message_payload).
        Raises:
            ConfigurationError, RuntimeError.
        """
        self._configure_logging(config_path) # Configure logging first

        try:
            self.config = load_config(config_path)
        except (ValueError, ConfigurationError) as e:
             logger.critical(f"CRITICAL CONFIGURATION ERROR: {e}. Node cannot start.")
             raise # Re-raise to halt execution

        self.node_id: int = self.config['node_id']
        self.role: NodeRole = NodeRole.INITIALIZING
        self._running = False # Flag to control main loop
        self.last_activity_time = time.monotonic()
        self.app_callback = application_callback
        self.failure_callback = on_send_failure_callback

        # Statistics Tracking
        self.stats = defaultdict(int)
        self.stats['start_time_monotonic'] = time.monotonic() # For uptime calculation

        # Initialize core components
        try:
            self.message_handler: MessageHandler = MessageHandler(self.node_id, self.config)
            self.cluster_manager: ClusterManager = ClusterManager(self) # Passes self (Node instance)
            self.power_manager: PowerManager = PowerManager(self.config)
            self.network: MeshtasticInterface = MeshtasticInterface(
                config=self.config,
                on_receive_callback=self._handle_incoming_packet,
                on_connection_callback=self._handle_connection_update
            )
            self.controller_logic: Optional[ControllerLogic] = None # Initialized on becoming controller
        except Exception as e:
             logger.critical(f"Failed to initialize core components: {e}", exc_info=True)
             raise RuntimeError(f"Node core component initialization failed: {e}")

        # Timers for periodic actions
        self.heartbeat_timer = Timer(self.config.get('heartbeat_interval', 60.0))
        self.discovery_timer = Timer(self.config.get('cluster_discovery_interval', 120.0))
        self.stats_log_interval = self.config.get('stats_log_interval', STATS_LOG_INTERVAL_DEFAULT)
        self.stats_timer = Timer(self.stats_log_interval if self.stats_log_interval > 0 else float('inf')) # Effectively disable if 0

        # For non-blocking ACK retries
        self._active_retry_timers: Set[threading.Timer] = set()
        self._retry_timer_lock = threading.Lock() # Protects _active_retry_timers

    def _configure_logging(self, config_path: str):
        """Sets up logging based on config file or defaults (internal helper)."""
        log_level_str_temp = "INFO" # Fallback
        try:
            # Minimal load just for log_level to avoid full validation errors here
            if os.path.exists(config_path):
                with open(config_path, 'r') as f_temp:
                    cfg_temp = json.load(f_temp)
                log_level_str_temp = cfg_temp.get('log_level', log_level_str_temp)
        except Exception:
            pass # Ignore errors, use fallback log_level_str_temp
        final_log_level = get_log_level(log_level_str_temp) # From config module
        setup_logging(level=final_log_level) # From utils module
        logger.info(f"Initial logging level set to: {logging.getLevelName(final_log_level)}")


    def run(self):
        """Main execution loop for the node."""
        if self._running:
            logger.warning("Node run() called but already running.")
            return

        logger.info(f"--- Starting AMCS Node {self.node_id} ---")
        self._running = True

        try:
            self.network.connect() # Attempt connection (non-blocking start)
            if self.stats_log_interval > 0: # Start stats timer only if interval is positive
                 self.stats_timer.start()

            while self._running:
                now_monotonic = time.monotonic()
                self._update_last_activity(now_monotonic) # Update activity for power manager

                # 1. Process Network State & Initial Role Transition
                if not self.network.is_connected:
                    if self.role != NodeRole.INITIALIZING:
                         logger.warning("Network disconnected. Resetting to INITIALIZING state.")
                         self._reset_to_initializing()
                    time.sleep(1.0) # Wait before re-checking connection
                    continue # Skip rest of loop if not connected

                if self.role == NodeRole.INITIALIZING: # Network just became connected
                     logger.info("Network connected. Transitioning to DISCOVERING.")
                     self._transition_role(NodeRole.DISCOVERING) # Handles timer starts
                     # Heartbeat timer started by _transition_role logic or by _perform_periodic_tasks on first run


                # 2. Determine and Update Role (based on ClusterManager state)
                # This needs to be done after network is confirmed connected and not initializing
                if self.role != NodeRole.INITIALIZING:
                    determined_role = self.cluster_manager.determine_current_role()
                    if determined_role != self.role:
                         self._transition_role(determined_role)


                # 3. Perform Role-Specific Periodic Tasks
                self._perform_periodic_tasks(now_monotonic)


                # 4. Check for Application-Level Timeouts (Direct ACKs)
                self._check_direct_ack_timeouts()


                # 5. Power Management Check
                self.power_manager.check_and_manage_sleep(self.network)


                time.sleep(0.1) # Main loop yield

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received. Initiating shutdown...")
        except Exception as e:
            logger.critical(f"CRITICAL UNEXPECTED ERROR in main loop: {e}", exc_info=True)
        finally:
            self.shutdown()


    def _reset_to_initializing(self):
        """Resets node state when network connection is lost or on explicit reset."""
        logger.warning(f"Node {self.node_id}: Resetting state to INITIALIZING.")
        previous_role = self.role
        self.role = NodeRole.INITIALIZING

        # Clean up components
        if self.controller_logic:
            self.controller_logic.stop_controller_tasks()
            self.controller_logic = None
        self.cluster_manager.leave_cluster() # Resets cluster state, stops election timer
        self.message_handler.clear_controller_queue() # Clear if was controller

        # Stop periodic task timers
        self.heartbeat_timer.stop()
        self.discovery_timer.stop()
        # Stats timer can keep running or be stopped: self.stats_timer.stop()

        # Attempt to reconnect if network object exists
        if self.network and not self.network.is_connected:
            logger.info("Attempting to re-establish network connection.")
            self.network.connect()


    def _transition_role(self, new_role: NodeRole):
        """Handles the logic and cleanup/setup when transitioning between roles."""
        if new_role == self.role: return

        logger.info(f"Node {self.node_id}: Role transition {self.role.name} -> {new_role.name} "
                    f"(Cluster: {self.cluster_manager.cluster_id}, Term: {self.cluster_manager.election_term})")
        self.stats[f'role_transition_{self.role.name}_to_{new_role.name}'] += 1
        previous_role = self.role
        self.role = new_role

        # --- Cleanup from previous role ---
        if previous_role == NodeRole.CONTROLLER and self.controller_logic:
            logger.info("Stopping controller logic tasks.")
            self.controller_logic.stop_controller_tasks()
            self.controller_logic = None
            self.message_handler.clear_controller_queue()

        # Stop timers based on previous role that might no longer be relevant
        if previous_role == NodeRole.DISCOVERING: self.discovery_timer.stop()
        if previous_role == NodeRole.ELECTION: self.cluster_manager.election_timer.stop()


        # --- Setup for new role ---
        if new_role == NodeRole.CONTROLLER:
            if not self.controller_logic: # Initialize if not already (e.g. first time)
                logger.info("Initializing controller logic...")
                self.controller_logic = ControllerLogic(self, self.stats) # Pass Node and stats
            self.discovery_timer.stop() # Controller doesn't discover
            self.cluster_manager.election_active = False # Ensure election definitely stops
            self.cluster_manager.election_timer.stop()
            if not self.heartbeat_timer.is_running(): self.heartbeat_timer.start() # Ensure heartbeats active

        elif new_role == NodeRole.MEMBER:
            self.discovery_timer.stop() # Member doesn't discover
            self.cluster_manager.election_active = False
            self.cluster_manager.election_timer.stop()
            if not self.heartbeat_timer.is_running(): self.heartbeat_timer.start()

        elif new_role == NodeRole.DISCOVERING:
            # Ensure we are not in a cluster state from previous role
            self.cluster_manager.leave_cluster() # Clears cluster_id, controller_id
            self.cluster_manager.election_active = False # Stop any election
            self.cluster_manager.election_timer.stop()
            # start_discovery will be called by periodic_tasks if timer expires or by initial transition
            if not self.discovery_timer.is_running():
                 self.cluster_manager.start_discovery() # Send initial probe
            if not self.heartbeat_timer.is_running(): self.heartbeat_timer.start()


        elif new_role == NodeRole.ELECTION:
            self.discovery_timer.stop() # Stop discovery during an election
            # Election timer itself is managed by ClusterManager.start_election()
            if not self.heartbeat_timer.is_running(): self.heartbeat_timer.start() # Still send heartbeats during election


    def _perform_periodic_tasks(self, current_time_monotonic: float):
        """Executes tasks based on timers and current role."""
        if self.role == NodeRole.INITIALIZING or not self.network.is_connected:
             return # No tasks until connected

        # --- Heartbeat (All connected roles) ---
        if self.heartbeat_timer.expired():
            logger.debug(f"Node {self.node_id} (Role: {self.role.name}) sending heartbeat.")
            hb_payload = {
                "role": self.role.name,
                "cluster_id": self.cluster_manager.cluster_id,
                "term": self.cluster_manager.election_term,
                "uptime_s": int(current_time_monotonic - self.stats['start_time_monotonic'])
            }
            hb_message = self.message_handler.create_message(MSG_TYPE_HEARTBEAT, hb_payload)
            try:
                self.send_amcs_message(hb_message) # Broadcasts, Node increments msgs_sent
                self.stats['heartbeats_sent'] += 1
            except NetworkError:
                 logger.warning("Failed to send heartbeat due to network error.")
            self.heartbeat_timer.reset()

        # --- Discovery Probes (Only when DISCOVERING) ---
        if self.role == NodeRole.DISCOVERING and self.discovery_timer.expired():
             logger.info(f"Node {self.node_id} sending cluster discovery request (Term: {self.cluster_manager.election_term}).")
             disc_req_payload = self.message_handler.create_message(MSG_TYPE_DISCOVERY_REQ)
             try:
                self.send_amcs_message(disc_req_payload) # Broadcasts
                self.stats['discovery_req_sent'] += 1
             except NetworkError:
                 logger.warning("Failed to send discovery request due to network error.")
             self.discovery_timer.reset()

        # --- Controller Tasks (Only when CONTROLLER) ---
        if self.role == NodeRole.CONTROLLER and self.controller_logic:
             self.controller_logic.perform_controller_tasks()

        # --- Cluster/Election/Sync Maintenance (All connected roles, except INITIALIZING) ---
        if self.role != NodeRole.INITIALIZING:
            self.cluster_manager.perform_maintenance()

        # --- Log Statistics Periodically ---
        if self.stats_timer.is_running() and self.stats_timer.expired():
            uptime_total_seconds = int(current_time_monotonic - self.stats['start_time_monotonic'])
            days, rem_uptime = divmod(uptime_total_seconds, 86400)
            hours, rem_uptime = divmod(rem_uptime, 3600)
            mins, secs = divmod(rem_uptime, 60)
            uptime_str = f"{days}d {hours:02}:{mins:02}:{secs:02}"

            logger.info(f"--- Node Statistics ({self.node_id} | Role: {self.role.name} | Cluster: {self.cluster_manager.cluster_id} | Term: {self.cluster_manager.election_term}) ---")
            logger.info(f"Uptime: {uptime_str}")
            for key, value in sorted(self.stats.items()):
                 if key not in ['start_time_monotonic']:
                    logger.info(f"{key.replace('_', ' ').capitalize():<28}: {value}")
            logger.info(f"{'Known Neighbors':<28}: {len(self.cluster_manager.neighbors)}")
            if self.role == NodeRole.CONTROLLER and self.message_handler.controller_queue is not None:
                 logger.info(f"{'Controller Queue Size':<28}: {len(self.message_handler.controller_queue)}")
            logger.info("-----------------------------------------------------------------")
            self.stats_timer.reset()


    def _check_direct_ack_timeouts(self):
        """ Checks ACK timeouts and schedules non-blocking retries or calls failure callback. """
        timed_out_acks = self.message_handler.check_ack_timeouts()
        # MAX_ACK_RETRIES and BASE_ACK_BACKOFF_DELAY defined as class/module constants

        for msg_id, dest_id_hex, original_payload, retries_so_far in timed_out_acks:
            if retries_so_far < MAX_ACK_RETRIES:
                # Calculate exponential backoff delay with jitter
                backoff_delay = BASE_ACK_BACKOFF_DELAY * (2 ** retries_so_far)
                jitter = random.uniform(-BASE_ACK_BACKOFF_DELAY / 2, BASE_ACK_BACKOFF_DELAY / 2)
                actual_delay = max(0.1, backoff_delay + jitter)

                next_attempt_num = retries_so_far + 1
                logger.warning(f"ACK timeout for {msg_id[-8:]} to {dest_id_hex}. Scheduling resend "
                               f"(Retry {next_attempt_num}/{MAX_ACK_RETRIES}) in {actual_delay:.2f}s.")
                try:
                    # Arguments for the _resend_direct_message method
                    timer_args = [msg_id, dest_id_hex, original_payload, next_attempt_num]
                    retry_timer = threading.Timer(actual_delay, lambda: None) # Placeholder target
                    retry_timer.function = self._resend_direct_message # Assign actual target
                    retry_timer.args = [retry_timer] + timer_args # Prepend timer_ref

                    with self._retry_timer_lock:
                        self._active_retry_timers.add(retry_timer)
                    retry_timer.start()

                    # Increment retry count in MessageHandler AFTER successfully scheduling
                    self.message_handler.increment_retry_count(msg_id)
                    self.stats['ack_timeouts_scheduled_retry'] += 1

                except Exception as e:
                    logger.exception(f"Failed to schedule ACK retry timer for {msg_id[-8:]}")
                    # If scheduling fails, this attempt is lost. Message will likely time out again if not ACKed.
            else:
                 logger.error(f"Gave up sending direct message {msg_id[-8:]} to {dest_id_hex} after {MAX_ACK_RETRIES} retries.")
                 self.stats['ack_timeouts_failed_max_retries'] += 1
                 if self.failure_callback:
                      try:
                           self.failure_callback(msg_id, dest_id_hex, original_payload)
                      except Exception as e:
                           logger.exception(f"Error executing on_send_failure_callback for msg {msg_id[-8:]}")
                 else:
                      logger.debug(f"Message send failed permanently for {msg_id[-8:]}, no failure callback registered.")


    def _resend_direct_message(self, timer_ref: threading.Timer, msg_id: str, dest_id_hex: str, original_payload: Dict, attempt_number: int):
        """ Executes scheduled resend for a direct message. Called by threading.Timer. """
        # Ensure timer removal from active set happens even if errors occur
        try:
            if not self._running:
                logger.warning(f"Resend for {msg_id[-8:]} cancelled: Node shutting down.")
                return
            if not self.network or not self.network.is_connected:
                logger.warning(f"Resend for {msg_id[-8:]} cancelled: Network disconnected.")
                # Do not re-track if network is down, will timeout again if network recovers
                return

            logger.info(f"Executing scheduled resend of {msg_id[-8:]} to {dest_id_hex} (Attempt {attempt_number}).")
            self.stats[f'ack_resend_attempt_{attempt_number}'] += 1

            # Attempt to send the message (uses internal send retries)
            self.send_amcs_message(original_payload, destination_id_hex=dest_id_hex)

            # If send_amcs_message succeeded (didn't raise error), re-track for ACK
            logger.debug(f"Resend successful (queued), re-tracking ACK for {msg_id[-8:]}")
            # track_for_ack preserves existing retry count, which was already incremented by caller (_check_direct_ack_timeouts)
            self.message_handler.track_for_ack(msg_id, dest_id_hex, original_payload)

        except (NetworkError, StateError) as e:
            logger.error(f"Scheduled resend failed for {msg_id[-8:]} to {dest_id_hex}: {e}")
            # Message will timeout again if still in pending_direct_acks and not max retries
            # (It was removed by check_ack_timeouts, so it won't be re-checked unless re-tracked here)
        except Exception as e:
            logger.exception(f"Unexpected error during scheduled resend of {msg_id[-8:]}")
        finally:
            with self._retry_timer_lock:
                self._active_retry_timers.discard(timer_ref)


    def _handle_connection_update(self, connection_info: Dict):
        """Callback from NetworkInterface when connection status changes."""
        self._update_last_activity()
        status = connection_info.get("status")
        node_info_from_conn = connection_info.get("node_info") # May be None
        logger.info(f"Network connection update: Status={status}. Node Info from event: {node_info_from_conn}")

        if status == "connected":
             # If node_info wasn't fetched during connect, it might be available now
             if node_info_from_conn:
                  self.network._node_info = node_info_from_conn # Update network's cached copy
                  logger.info(f"Node info updated from connection event: {node_info_from_conn.get('long_name', node_info_from_conn.get('node_id_hex'))}")
             # Main loop handles transition from INITIALIZING based on network.is_connected
        elif status == "disconnected":
             logger.warning(f"Network reported DISCONNECTED. Node {self.node_id} will reset if state was active.")
             # Main loop's check on network.is_connected will trigger _reset_to_initializing


    def _handle_incoming_packet(self, packet_data: Dict):
        """ Callback from NetworkInterface for processing received AMCS packets. """
        now_monotonic = time.monotonic()
        self._update_last_activity(now_monotonic)

        try:
            sender_mesh_id = packet_data.get('from_id_hex')
            message = packet_data.get('payload') # Decoded AMCS message dict
            rssi = packet_data.get('rssi')
            snr = packet_data.get('snr')

            # Basic validation of AMCS message structure
            if not isinstance(message, dict):
                logger.warning(f"Ignoring non-dict AMCS payload from {sender_mesh_id}. PacketData: {packet_data}")
                return

            msg_type = message.get("type")
            msg_id = message.get("id")
            sender_amcs_id = message.get("from") # This is AMCS Node ID

            if not all([msg_type, msg_id, sender_amcs_id is not None]): # from can be 0 but not None
                 logger.warning(f"Ignoring incomplete AMCS message from {sender_mesh_id}: Fields missing. Message: {message}")
                 self.stats['malformed_headers_recv'] += 1
                 return

            if sender_amcs_id == self.node_id: # Ignore self-echoed messages
                 # logger.debug(f"Ignoring own echoed message {msg_id[-8:]}")
                 return

            log_prefix = f"Node {self.node_id} (Role:{self.role.name}, Cl:{self.cluster_manager.cluster_id}, T:{self.cluster_manager.election_term})"
            logger.debug(f"{log_prefix} RX {msg_type} ({msg_id[-8:]}) from AMCS Node {sender_amcs_id} ({sender_mesh_id}, RSSI:{rssi}, SNR:{snr})")
            logger.debug(f"{log_prefix} RX Payload: {message.get('p')}") # Log payload content at DEBUG

            self.stats['msgs_recv'] += 1

            # --- Duplicate Check ---
            is_dup = self.message_handler.is_duplicate(msg_id)

            # --- Send ACK for non-ACK messages (even if duplicate, sender might have missed original ACK) ---
            if msg_type != MSG_TYPE_ACK and sender_mesh_id: # Ensure sender_mesh_id is known for direct reply
                self.send_ack(msg_id, sender_mesh_id) # Node method increments acks_sent stat

            if is_dup:
                logger.debug(f"{log_prefix} Ignoring duplicate msg {msg_id[-8:]} from {sender_amcs_id} (ACK already sent if needed).")
                self.stats['duplicates_recv'] += 1
                return

            # Store message (ID for future dup check, payload for sync) *after* duplicate check
            # but *before* further processing to prevent re-processing on error.
            self.message_handler.store_message(msg_id, message)


            # --- Process based on Message Type ---
            if msg_type == MSG_TYPE_APP_DATA:
                 app_payload_wrapper = message.get('p')
                 if not isinstance(app_payload_wrapper, dict) or 'app_data' not in app_payload_wrapper:
                      logger.warning(f"{log_prefix} Malformed APP_DATA payload from {sender_amcs_id}: {app_payload_wrapper}")
                      self.stats['malformed_payloads_recv'] += 1; return
                 app_payload = app_payload_wrapper['app_data']

                 if self.role == NodeRole.CONTROLLER and self.controller_logic:
                     self.controller_logic.handle_incoming_message(message, sender_mesh_id)
                 elif self.role == NodeRole.MEMBER and sender_amcs_id == self.cluster_manager.controller_amcs_id:
                     logger.info(f"{log_prefix} RX APP_DATA {msg_id[-8:]} from Controller {sender_amcs_id}. Relaying to app.")
                     self.stats['app_data_recv_processed'] += 1
                     if self.app_callback:
                         try: self.app_callback(app_payload)
                         except Exception as e: logger.exception("Error in application_callback for APP_DATA")
                     else: logger.debug("No application_callback registered for APP_DATA.")
                 else:
                     logger.debug(f"{log_prefix} Ignoring APP_DATA {msg_id[-8:]} (not controller, or not from my controller). Sender: {sender_amcs_id}")

            elif msg_type == MSG_TYPE_ACK:
                 payload = message.get("p", {})
                 acked_msg_id = payload.get("ack_id")
                 if not acked_msg_id or not isinstance(acked_msg_id, str):
                      logger.warning(f"{log_prefix} Malformed ACK payload from {sender_amcs_id}: {payload}")
                      self.stats['malformed_payloads_recv'] += 1; return

                 self.stats['acks_recv'] += 1
                 processed_ack_flag = False
                 if self.role == NodeRole.CONTROLLER and self.controller_logic:
                     processed_ack_flag = self.controller_logic.handle_incoming_message(message, sender_mesh_id)
                 else: # Non-controller handles direct ACKs
                     processed_ack_flag = self.message_handler.process_ack(acked_msg_id, sender_amcs_id, sender_mesh_id or "UnknownMeshFromACK")
                 if processed_ack_flag: self.stats['acks_recv_processed'] += 1


            elif msg_type == MSG_TYPE_HEARTBEAT:
                 payload = message.get("p", {})
                 if not all(k in payload for k in ("role", "cluster_id", "term")):
                      logger.warning(f"{log_prefix} Malformed HEARTBEAT payload from {sender_amcs_id}: {payload}")
                      self.stats['malformed_payloads_recv'] += 1; return
                 self.stats['heartbeats_recv'] += 1
                 self.cluster_manager.process_heartbeat(message, sender_mesh_id, rssi, snr)

            # (Dispatch to ClusterManager for Discovery and Election types)
            elif msg_type == MSG_TYPE_DISCOVERY_REQ:
                self.stats['discovery_req_recv'] += 1
                self.cluster_manager.process_discovery_request(message, sender_mesh_id)
            elif msg_type == MSG_TYPE_DISCOVERY_RESP:
                self.stats['discovery_resp_recv'] += 1
                self.cluster_manager.process_discovery_response(message, sender_mesh_id, rssi, snr)
            elif msg_type == MSG_TYPE_ELECTION_REQUEST:
                self.stats['election_req_recv'] += 1
                self.cluster_manager.process_election_request(message, sender_mesh_id)
            elif msg_type == MSG_TYPE_ELECTION_VOTE:
                self.stats['election_votes_recv'] += 1
                self.cluster_manager.process_election_vote(message, sender_mesh_id)
            elif msg_type == MSG_TYPE_ELECTION_WINNER:
                self.stats['election_winner_recv'] += 1
                self.cluster_manager.process_election_winner(message, sender_mesh_id)

            # Neighbor Sync Handling
            elif msg_type == MSG_TYPE_SYNC_INFO:
                 self.stats['sync_info_recv'] += 1
                 self.cluster_manager.process_sync_info(message, sender_mesh_id)
            elif msg_type == MSG_TYPE_SYNC_REQ:
                 self.stats['sync_req_recv'] += 1
                 self.cluster_manager.process_sync_request(message, sender_mesh_id)
            elif msg_type == MSG_TYPE_MISSING_MSG_REQ:
                 self.stats['sync_mreq_recv'] += 1
                 self.cluster_manager.process_missing_message_request(message, sender_mesh_id)
            elif msg_type == MSG_TYPE_MISSING_MSG_RESP:
                 self.stats['sync_mresp_recv'] += 1
                 self.cluster_manager.process_missing_message_response(message, sender_mesh_id)

            else:
                 logger.warning(f"{log_prefix} Received unhandled message type '{msg_type}' from {sender_amcs_id}")
                 self.stats['unknown_msgs_recv'] += 1

        except MessageError as e:
             logger.error(f"{log_prefix} Message handling error: {e}", exc_info=True)
        except Exception as e:
             logger.exception(f"{log_prefix} Critical error processing incoming packet: {packet_data}")


    def send_ack(self, original_msg_id: str, destination_mesh_id: str):
        """Helper method to create and send an ACK message directly to a mesh node."""
        try:
            ack_message = self.message_handler.create_ack(original_msg_id)
            logger.debug(f"Node {self.node_id}: Sending ACK for {original_msg_id[-8:]} to {destination_mesh_id}")
            # send_amcs_message handles its own try-except for network send
            self.send_amcs_message(ack_message, destination_id_hex=destination_mesh_id)
            self.stats['acks_sent'] += 1
        except Exception as e: # Catch errors from message creation or if send_amcs_message re-raises
            logger.error(f"Node {self.node_id}: Failed to send ACK for {original_msg_id[-8:]}: {e}", exc_info=True)
            self.stats['acks_failed_send'] += 1


    def send_amcs_message(self, payload_dict: Dict, destination_id_hex: Optional[str] = None):
        """
        Sends an AMCS message using the network interface. Includes stats and retry logic.
        """
        if not self._running: raise StateError("Cannot send message, node is not running.")
        if not self.network or not self.network.is_connected:
            raise NetworkError("Cannot send message, network not connected.")

        if destination_id_hex is None: destination_id_hex = "!ffffffff" # Meshtastic broadcast

        msg_type_log = payload_dict.get('type', 'UNK')
        msg_id_log = payload_dict.get('id', 'N/A')[-8:]
        log_prefix = f"Node {self.node_id} (Role:{self.role.name}, Cl:{self.cluster_manager.cluster_id}, T:{self.cluster_manager.election_term})"
        logger.debug(f"{log_prefix} TX {msg_type_log} ({msg_id_log}) to {destination_id_hex}. Payload: {payload_dict.get('p')}")

        # Use constants for send attempts
        for attempt in range(MAX_SEND_ATTEMPTS):
             try:
                  self.network.send_message(payload_dict, destination_id_hex=destination_id_hex)
                  self._update_last_activity() # Mark activity on successful queueing
                  # Increment general msgs_sent only on first successful attempt
                  if attempt == 0: self.stats['msgs_sent'] += 1
                  # Could add type-specific sent stats here too if desired:
                  # self.stats[f"sent_{msg_type_log}"] += 1
                  logger.debug(f"Send attempt {attempt + 1} for {msg_id_log} successful (queued).")
                  return # Exit on success

             except NetworkError as e:
                  logger.warning(f"{log_prefix} NetworkError sending {msg_id_log} (Attempt {attempt + 1}/{MAX_SEND_ATTEMPTS}): {e}")
                  if attempt < MAX_SEND_ATTEMPTS - 1:
                       logger.info(f"Retrying send of {msg_id_log} in {SEND_RETRY_DELAY} seconds...")
                       time.sleep(SEND_RETRY_DELAY) # Blocking sleep, consider alternatives if too impactful
                  else:
                       logger.error(f"{log_prefix} Send of {msg_id_log} failed after {MAX_SEND_ATTEMPTS} attempts.")
                       self.stats['msgs_failed_send'] += 1
                       raise # Re-raise the final NetworkError
             except Exception as e:
                  logger.exception(f"{log_prefix} Unexpected error sending {msg_id_log} (Attempt {attempt + 1})")
                  if attempt == MAX_SEND_ATTEMPTS - 1:
                       self.stats['msgs_failed_send'] += 1
                       raise NetworkError(f"Unexpected send error for {msg_id_log}: {e}") # Wrap as NetworkError

        # Fallback if loop completes without success or exception (should not happen)
        logger.error(f"{log_prefix} Send of {msg_id_log} failed unexpectedly after all attempts.")
        self.stats['msgs_failed_send'] += 1
        raise NetworkError(f"Send of {msg_id_log} failed after {MAX_SEND_ATTEMPTS} attempts, reason unknown.")


    def send_application_data(self, data: Any) -> Optional[str]:
         """ Public method for applications to send data. Includes stats. """
         logger.info(f"Node {self.node_id}: Request to send application data: {str(data)[:80]}...") # Log truncated data
         self._update_last_activity()

         if not self._running or self.role == NodeRole.INITIALIZING:
             logger.error("Cannot send app data: Node not running or still initializing.")
             return None
         if not self.network or not self.network.is_connected:
             logger.error("Cannot send app data: Network not connected.")
             return None

         msg_id = None # Initialize in case of early exit
         try:
            app_message = self.message_handler.create_message(MSG_TYPE_APP_DATA, payload={"app_data": data})
            msg_id = app_message["id"]
         except Exception as e:
             logger.exception("Failed to create application message object")
             return None

         try:
            if self.role == NodeRole.CONTROLLER and self.controller_logic:
                logger.info(f"Node {self.node_id} (Controller) handling own app data ({msg_id[-8:]}).")
                # Controller logic handles queueing, broadcasting, and its own stats
                self.controller_logic.handle_incoming_message(app_message, self.network.get_node_info().get('node_id_hex') if self.network.get_node_info() else None)
                self.stats['app_data_sent_as_controller'] += 1
                return msg_id

            elif self.role == NodeRole.MEMBER and self.cluster_manager.controller_mesh_id:
                controller_dest_id = self.cluster_manager.controller_mesh_id
                logger.info(f"Node {self.node_id} (Member) sending app data ({msg_id[-8:]}) to Controller {self.cluster_manager.controller_amcs_id} ({controller_dest_id})")
                # send_amcs_message handles its own msgs_sent stat
                self.send_amcs_message(app_message, destination_id_hex=controller_dest_id)
                # Track ACK from the controller for this direct message
                self.message_handler.track_for_ack(msg_id, controller_dest_id, app_message)
                self.stats['app_data_sent_to_controller'] += 1
                return msg_id

            elif self.role in [NodeRole.DISCOVERING, NodeRole.ELECTION]:
                 logger.warning(f"Cannot send app data: Node role is {self.role.name}. No established controller.")
                 self.stats['app_data_send_failed_no_controller'] += 1
                 return None
            else: # Should not happen
                 logger.error(f"Cannot send app data in unexpected role: {self.role.name}")
                 return None

         except (NetworkError, StateError, MessageError) as e: # Catch specific AMCS errors
              logger.error(f"Failed to send application data ({msg_id[-8:] if msg_id else 'N/A'}): {e}")
              return None
         except Exception as e: # Catch any other unexpected errors
              logger.exception(f"Unexpected error sending application data ({msg_id[-8:] if msg_id else 'N/A'})")
              return None


    def _update_last_activity(self, timestamp: Optional[float] = None):
        """Updates the last activity timestamp for power management."""
        now_mono = timestamp if timestamp else time.monotonic()
        self.last_activity_time = now_mono
        self.power_manager.update_activity(now_mono)


    def shutdown(self):
        """ Initiates graceful shutdown of the node. """
        if not self._running and not self._active_retry_timers : # Check if already shut down or shutting down
             logger.debug(f"Node {self.node_id} shutdown already called or not running.")
             return

        logger.info(f"--- Shutting down AMCS Node {self.node_id} ---")
        self._running = False # Signal main loop and other processes to stop

        # Cancel active ACK retry timers
        logger.debug("Cancelling active ACK retry timers...")
        with self._retry_timer_lock:
            active_timers_copy = list(self._active_retry_timers)
            for timer in active_timers_copy:
                try: timer.cancel()
                except Exception as e: logger.warning(f"Error cancelling timer {timer}: {e}")
            self._active_retry_timers.clear()
        logger.debug(f"{len(active_timers_copy)} ACK retry timers cancelled.")

        # Stop controller tasks if active
        if self.controller_logic:
            self.controller_logic.stop_controller_tasks()
            self.controller_logic = None # Clear reference

        # Stop periodic node timers
        self.heartbeat_timer.stop()
        self.discovery_timer.stop()
        self.stats_timer.stop()
        if hasattr(self.cluster_manager, 'election_timer'): # Defensive
            self.cluster_manager.election_timer.stop()
        if hasattr(self.cluster_manager, 'sync_timer'): # Defensive
            self.cluster_manager.sync_timer.stop()

        # Close network connection
        if self.network:
            self.network.close()
            self.network = None # Clear reference

        logger.info(f"Node {self.node_id} shutdown sequence complete.")
