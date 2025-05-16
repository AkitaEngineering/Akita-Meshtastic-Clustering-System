# Copyright (c) 2025 Akita Engineering <https://www.akitaengineering.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import time
import logging
from typing import Dict, Any, Optional, Set, Tuple, List, Deque
from collections import deque, OrderedDict # Import OrderedDict
import json # Needed for size estimation if done here

from .utils import generate_message_id
from .exceptions import MessageError

logger = logging.getLogger(__name__)

# --- Message Types Constants ---
MSG_TYPE_APP_DATA = "APP"
MSG_TYPE_HEARTBEAT = "HBEAT"
MSG_TYPE_ACK = "ACK"
MSG_TYPE_DISCOVERY_REQ = "DREQ"
MSG_TYPE_DISCOVERY_RESP = "DRESP"
MSG_TYPE_ELECTION_REQUEST = "EREQ"
MSG_TYPE_ELECTION_VOTE = "VOTE"
MSG_TYPE_ELECTION_WINNER = "EWIN"
MSG_TYPE_SYNC_INFO = "SINFO"
MSG_TYPE_SYNC_REQ = "SREQ"
MSG_TYPE_MISSING_MSG_REQ = "MREQ"
MSG_TYPE_MISSING_MSG_RESP = "MRESP"


class MessageHandler:
    """
    Handles message creation, parsing, tracking (duplicates, ACKs), and storage.
    Manages pending ACKs, duplicate ID checking, and stores message payloads for sync.
    """

    def __init__(self, node_id: int, config: Dict[str, Any]):
        """
        Initializes the MessageHandler.

        Args:
            node_id (int): The AMCS node ID of the parent node.
            config (Dict[str, Any]): The node's configuration dictionary.

        Raises:
            MessageError: If node_id is None.
        """
        if node_id is None: raise MessageError("MessageHandler requires a valid node_id.")
        self.node_id = node_id
        self.config = config
        self.ack_timeout_duration = config.get("ack_timeout", 15.0)

        # For duplicate checking (IDs only)
        self.retention_count_ids = config.get("message_retention_count", 100)
        if self.retention_count_ids <= 0:
             logger.warning("message_retention_count is <= 0, duplicate checking will be limited or disabled.")
             self.received_message_ids: Optional[Deque[str]] = None
        else:
             self.received_message_ids: Optional[Deque[str]] = deque(maxlen=self.retention_count_ids)

        # For storing message payloads (for potential retrieval in neighbor sync)
        self.payload_retention_count = config.get("message_payload_retention_count", 200)
        self.payload_retention_seconds = config.get("message_payload_retention_seconds", 3600.0)
        self.message_payload_store: OrderedDict[str, Dict] = OrderedDict()
        self._last_age_prune_time = 0.0
        # How often to check for age pruning, relative to payload_retention_seconds or fixed.
        self.age_prune_interval = max(60.0, self.payload_retention_seconds / 10 if self.payload_retention_seconds > 0 else 600.0)


        # For tracking direct ACKs
        # {msg_id: {'sent_time': float, 'destination_id_hex': str, 'payload': Dict, 'retries': int}}
        self.pending_direct_acks: Dict[str, Dict] = {}

        # For controller message queue
        # {msg_id: { 'payload': Dict, 'acked_by': Set[int], 'first_sent': float, 'last_broadcast': float}}
        self.controller_queue: Dict[str, Dict] = {}

    def create_message(self, msg_type: str, payload: Optional[Dict] = None, msg_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a standard AMCS message dictionary with required fields.

        Args:
            msg_type (str): One of the MSG_TYPE constants.
            payload (Optional[Dict]): Type-specific data dictionary.
            msg_id (Optional[str]): Specific message ID override.

        Returns:
            Dict[str, Any]: The constructed message dictionary.
        """
        if msg_id is None: msg_id = generate_message_id()
        if payload is None: payload = {}
        message = {
            "type": msg_type,
            "id": msg_id,       # Shortened key for space
            "from": self.node_id, # AMCS Node ID of the sender
            "ts": int(time.time()), # Timestamp (integer seconds)
            "p": payload        # Shortened key for space (payload)
        }
        return message

    def create_ack(self, original_msg_id: str) -> Dict[str, Any]:
        """Creates an ACK message payload for a given original message ID."""
        return self.create_message(MSG_TYPE_ACK, payload={"ack_id": original_msg_id})

    def is_duplicate(self, msg_id: str) -> bool:
        """Checks if a message ID has been seen recently (based on ID deque)."""
        if self.received_message_ids is None: return False # Duplicate check effectively disabled
        return msg_id in self.received_message_ids

    def store_message(self, msg_id: str, message_payload: Dict):
        """
        Stores a received message's ID (for duplicate checks) and its payload (for potential sync responses).
        Handles pruning of both ID deque and payload store based on configured limits.

        Args:
            msg_id: The unique ID of the message.
            message_payload: The full dictionary payload of the message to store.
        """
        if msg_id is None or message_payload is None:
            logger.warning("Attempted to store None msg_id or message_payload.")
            return

        now = time.time() # Get current time once

        # 1. Add ID to recent ID deque (if enabled for duplicate checks)
        if self.received_message_ids is not None and msg_id not in self.received_message_ids:
            self.received_message_ids.append(msg_id) # Deque handles maxlen

        # 2. Add full payload to the payload store (OrderedDict for easy pruning by count)
        # Only store if payload retention count is positive
        if self.payload_retention_count > 0:
            if msg_id in self.message_payload_store:
                # Message seen again (e.g., processed after sync), move to end to refresh position
                self.message_payload_store.move_to_end(msg_id)
            else:
                # Add new message
                self.message_payload_store[msg_id] = message_payload
                # Prune oldest by count immediately if store exceeds limit
                while len(self.message_payload_store) > self.payload_retention_count:
                    try:
                        oldest_id, _ = self.message_payload_store.popitem(last=False) # FIFO removal
                        logger.debug(f"Pruned oldest message payload from store by count: {oldest_id[-8:]}")
                    except KeyError:
                         # Store became empty during concurrent modification? Should be rare.
                         break

        # 3. Prune by age periodically (less frequent check for efficiency)
        # Only if payload retention by seconds is enabled
        if self.payload_retention_seconds > 0 and (now - self._last_age_prune_time) > self.age_prune_interval:
             self._prune_payload_store_by_age(now)
             self._last_age_prune_time = now


    def _prune_payload_store_by_age(self, current_time: float):
        """Internal helper to prune the payload store based on timestamp."""
        if self.payload_retention_seconds <= 0 or not self.message_payload_store: return # Disabled or empty

        pruned_count = 0
        ids_to_prune = []
        # Iterate from oldest (OrderedDict preserves insertion order)
        for msg_id, payload in self.message_payload_store.items():
            msg_ts = payload.get("ts", 0) # Get timestamp from stored message
            if (current_time - msg_ts) > self.payload_retention_seconds:
                ids_to_prune.append(msg_id)
            else:
                 # Since items are ordered by insertion (roughly time), we can stop early
                 break

        if ids_to_prune:
            for msg_id_to_prune in ids_to_prune:
                # Check if still present as count pruning might have occurred concurrently? Unlikely here.
                if msg_id_to_prune in self.message_payload_store:
                     del self.message_payload_store[msg_id_to_prune]
                     pruned_count += 1
            logger.info(f"Pruned {pruned_count} message payloads by age.")


    def get_stored_message(self, msg_id: str) -> Optional[Dict]:
        """Retrieves a stored message payload by its ID."""
        return self.message_payload_store.get(msg_id)

    def get_recent_message_ids(self) -> List[str]:
        """Returns a list of recently received message IDs (from the duplicate check deque)."""
        if self.received_message_ids is None: return []
        # Return a copy of the deque's contents
        return list(self.received_message_ids)


    def track_for_ack(self, msg_id: str, destination_id_hex: str, original_payload: Dict):
        """
        Starts or updates tracking for a sent message that requires an ACK from a specific destination.
        If the message is already tracked, it updates the sent_time but preserves the retry count.
        """
        existing_retries = 0
        if msg_id in self.pending_direct_acks:
            existing_retries = self.pending_direct_acks[msg_id].get('retries', 0)
            logger.debug(f"Updating tracking for already tracked message {msg_id[-8:]}. Preserving retry count ({existing_retries}).")
        else:
            logger.debug(f"Tracking direct message {msg_id[-8:]} for ACK from {destination_id_hex}")

        self.pending_direct_acks[msg_id] = {
            'sent_time': time.monotonic(), # Update sent time for timeout calculation
            'destination_id_hex': destination_id_hex,
            'payload': original_payload,
            'retries': existing_retries # Use existing count or 0
        }

    def increment_retry_count(self, msg_id: str):
        """Increments the retry count for a tracked direct ACK message."""
        if msg_id in self.pending_direct_acks:
             self.pending_direct_acks[msg_id]['retries'] += 1
        else:
             # This might happen if ACK arrived just before resend executed, or if msg was pruned
             logger.debug(f"Attempted to increment retry count for untracked/pruned message {msg_id[-8:]}")


    def process_ack(self, acked_msg_id: str, sender_amcs_id: int, sender_mesh_id_hex: str) -> bool:
        """
        Processes a received ACK message. Checks both direct pending ACKs and the controller queue.

        Returns:
            True if the ACK was relevant and processed, False otherwise.
        """
        processed = False

        # 1. Check if it ACKs a message sent directly by this node
        if acked_msg_id in self.pending_direct_acks:
            ack_info = self.pending_direct_acks[acked_msg_id]
            rtt = time.monotonic() - ack_info['sent_time']
            retries_taken = ack_info['retries'] # Get retry count when ACK received
            logger.info(f"Received direct ACK for msg {acked_msg_id[-8:]} from {sender_mesh_id_hex} (Node {sender_amcs_id}). RTT: {rtt:.2f}s, Retries: {retries_taken}")
            del self.pending_direct_acks[acked_msg_id]
            processed = True

        # 2. Check if it ACKs a message in the controller queue (if this node is controller)
        if acked_msg_id in self.controller_queue:
            if 'acked_by' not in self.controller_queue[acked_msg_id]:
                self.controller_queue[acked_msg_id]['acked_by'] = set()

            if sender_amcs_id not in self.controller_queue[acked_msg_id]['acked_by']:
                 self.controller_queue[acked_msg_id]['acked_by'].add(sender_amcs_id)
                 logger.debug(f"Controller received ACK for {acked_msg_id[-8:]} from node {sender_amcs_id}. "
                             f"Total ACKs for this msg: {len(self.controller_queue[acked_msg_id]['acked_by'])}")
                 processed = True # Count as processed
            else:
                 # Already had ACK from this sender for this message
                 logger.debug(f"Received duplicate controller ACK for {acked_msg_id[-8:]} from node {sender_amcs_id}")
                 processed = True # Still counts as processed for stats if needed, even if duplicate ACK

        if not processed:
             logger.debug(f"Received ACK for untracked/unknown message {acked_msg_id[-8:]} from {sender_amcs_id}")
        return processed

    def check_ack_timeouts(self) -> List[Tuple[str, str, Dict, int]]:
        """
        Checks pending direct ACKs for timeouts.

        Returns:
            A list of tuples for timed-out messages: (msg_id, destination_id_hex, original_payload, retries_so_far)
        """
        timed_out: List[Tuple[str, str, Dict, int]] = []
        current_time = time.monotonic()
        # Iterate over a copy of keys to allow deletion during iteration
        for msg_id in list(self.pending_direct_acks.keys()):
            ack_info = self.pending_direct_acks[msg_id]
            if (current_time - ack_info['sent_time']) > self.ack_timeout_duration:
                retries_so_far = ack_info['retries'] # Current retry count for this message
                logger.warning(f"ACK timeout for direct message {msg_id[-8:]} to {ack_info['destination_id_hex']} (Had {retries_so_far} retries)")
                timed_out.append((msg_id, ack_info['destination_id_hex'], ack_info['payload'], retries_so_far))
                # Remove from pending list after identifying timeout; Node will re-track if retrying
                del self.pending_direct_acks[msg_id]
        return timed_out

    # --- Controller Specific Queue Management ---

    def add_to_controller_queue(self, msg_payload: Dict):
        """Adds a message (usually APP_DATA) to the controller's queue for distribution."""
        msg_id = msg_payload.get("id")
        if not msg_id:
            logger.error("Message payload missing 'id', cannot add to controller queue.")
            return

        if msg_id not in self.controller_queue:
            sender_id = msg_payload.get("from")
            self.controller_queue[msg_id] = {
                'payload': msg_payload,
                'acked_by': set(), # Set of AMCS Node IDs that have ACKed this broadcast
                'first_sent': time.monotonic(),
                'last_broadcast': time.monotonic()
            }
            logger.info(f"Controller queued message {msg_id[-8:]} from node {sender_id}")
        else:
            logger.debug(f"Message {msg_id[-8:]} already in controller queue.")


    def get_messages_needing_rebroadcast(self, cluster_member_ids: Set[int]) -> List[Tuple[Dict, Set[int]]]:
        """
        Identifies messages in the controller queue that need rebroadcasting.
        Args:
            cluster_member_ids: Set of current AMCS node IDs in the cluster (excluding the controller itself).
        Returns:
            List of tuples: (message_payload_to_rebroadcast, set_of_nodes_needing_it)
        """
        needs_rebroadcast: List[Tuple[Dict, Set[int]]] = []
        current_time = time.monotonic()
        check_time_threshold = self.ack_timeout_duration + self.config.get("rebroadcast_delay", 5.0)

        if not cluster_member_ids:
             # logger.debug("Controller has no members to rebroadcast to currently.")
             return []

        for msg_id, data in list(self.controller_queue.items()):
            time_since_last_broadcast = current_time - data.get('last_broadcast', data['first_sent'])

            if time_since_last_broadcast >= check_time_threshold:
                acked_nodes = data.get('acked_by', set())
                missing_nodes = cluster_member_ids - acked_nodes

                if missing_nodes:
                    logger.warning(f"Message {msg_id[-8:]} needs rebroadcast. Missing ACKs from: {missing_nodes}")
                    needs_rebroadcast.append((data['payload'], missing_nodes))
                    data['last_broadcast'] = current_time # Update last broadcast time immediately
        return needs_rebroadcast


    def prune_controller_queue(self, current_cluster_members: Set[int], max_age_seconds: Optional[float] = None):
        """ Removes messages from the controller queue that are fully ACKed or too old. """
        pruned_count = 0
        current_time = time.monotonic()

        for msg_id in list(self.controller_queue.keys()): # Iterate copy to allow deletion
            data = self.controller_queue.get(msg_id)
            if not data: continue # Should not happen if iterating keys()

            acked_nodes = data.get('acked_by', set())

            # Prune if all *current* members have acknowledged
            if current_cluster_members and current_cluster_members.issubset(acked_nodes):
                 logger.info(f"Pruning msg {msg_id[-8:]} (ACKed by all {len(current_cluster_members)} current members).")
                 del self.controller_queue[msg_id]
                 pruned_count += 1
                 continue

            # Prune if message is older than max_age_seconds
            if max_age_seconds and max_age_seconds > 0:
                 age = current_time - data.get('first_sent', current_time) # Use current_time if first_sent missing
                 if age > max_age_seconds:
                      missing_from = current_cluster_members - acked_nodes if current_cluster_members else "N/A"
                      logger.warning(f"Pruning msg {msg_id[-8:]} due to age ({age:.0f}s > {max_age_seconds:.0f}s). "
                                   f"ACKed by: {len(acked_nodes)}, Missing from: {missing_from}")
                      del self.controller_queue[msg_id]
                      pruned_count += 1
                      continue

        if pruned_count > 0:
            logger.debug(f"Pruned {pruned_count} messages from controller queue.")

    def clear_controller_queue(self):
        """Clears the entire controller message queue."""
        if self.controller_queue:
            logger.info(f"Clearing {len(self.controller_queue)} messages from controller queue.")
            self.controller_queue.clear()
