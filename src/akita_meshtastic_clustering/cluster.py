# Copyright (c) 2025 Akita Engineering <https://www.akitaengineering.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import time
import logging
import random
import json # Needed for size estimation in MRESP
from typing import Dict, Any, Optional, Set, Callable, Tuple, TYPE_CHECKING, List

if TYPE_CHECKING:
    from .node import Node, NodeRole # NodeRole is an enum
    from .messaging import MessageHandler

# Import message types needed
from .messaging import (MSG_TYPE_DISCOVERY_REQ, MSG_TYPE_DISCOVERY_RESP,
                        MSG_TYPE_ELECTION_REQUEST, MSG_TYPE_ELECTION_VOTE, MSG_TYPE_ELECTION_WINNER,
                        MSG_TYPE_SYNC_INFO, MSG_TYPE_SYNC_REQ,
                        MSG_TYPE_MISSING_MSG_REQ, MSG_TYPE_MISSING_MSG_RESP)
from .utils import Timer
from .exceptions import ConfigurationError, StateError, MessageError

logger = logging.getLogger(__name__)

# Constants for Neighbor Sync
DEFAULT_SYNC_INTERVAL = 180.0 # How often to initiate sync
DEFAULT_MAX_MISSING_IDS_PER_REQ = 10 # Max IDs to ask for at once (reduced from 20 for smaller MREQ)
DEFAULT_MAX_MSGS_PER_RESP = 3    # Max full messages per MRESP (tune based on typical msg size)
# Estimate max bytes for the 'msgs' list payload within an MRESP,
# leaving room for other MRESP fields & AMCS/Meshtastic overhead.
# Tune this based on observed Meshtastic packet limits (~230 total bytes common)
DEFAULT_MAX_MRESP_MSGS_PAYLOAD_BYTES = 180

class ClusterManager:
    """
    Manages cluster state, discovery, membership, controller election, and neighbor sync logic for a node.
    Requires references to Node's methods/state for full functionality.
    """

    def __init__(self, node_ref: 'Node'):
        """
        Initializes the ClusterManager.
        Args:
            node_ref (Node): A reference to the parent Node instance.
        """
        from .node import NodeRole # Local import for enum to avoid circular import issues at module level
        self.NodeRole = NodeRole # Store enum for later use

        self.node = node_ref
        self.node_id: int = self.node.node_id
        self.config: Dict[str, Any] = self.node.config
        self.message_handler: 'MessageHandler' = self.node.message_handler

        # Cluster State
        self.cluster_id: Optional[int] = None
        self.controller_amcs_id: Optional[int] = None
        self.controller_mesh_id: Optional[str] = None
        self.last_controller_heartbeat: float = 0.0
        self.joined_cluster_time: float = 0.0
        self.controller_timeouts_consecutive: int = 0

        # Neighbor State
        self.neighbors: Dict[int, Dict[str, Any]] = {} # amcs_id -> {mesh_id, last_seen, role, cluster_id, rssi, snr}
        self.neighbor_timeout_duration = self.config.get("controller_timeout", 180.0) # Using controller_timeout for neighbors
        self._last_neighbor_log_time = 0.0
        self.neighbor_log_interval = self.config.get("neighbor_log_interval", 120.0) # Add to config.py if customizable

        # Election State
        self.election_active: bool = False
        self.election_term: int = 0
        self.voted_in_term: int = -1
        self.votes_received: Dict[int, Dict[int, int]] = {} # Term -> CandidateID -> VoteCount
        self.election_timer = Timer(self.config.get("election_timeout", 30.0))
        self.election_candidate_id: Optional[int] = None # Candidate this node voted for in current term

        # Neighbor Sync State / Timers
        self.sync_interval = self.config.get("sync_interval", DEFAULT_SYNC_INTERVAL)
        self.sync_timer = Timer(self.sync_interval)
        self.max_missing_ids_per_request = self.config.get("max_missing_ids_per_req", DEFAULT_MAX_MISSING_IDS_PER_REQ)
        self.max_msgs_per_resp = self.config.get("max_msgs_per_resp", DEFAULT_MAX_MSGS_PER_RESP)
        self.max_mresp_payload_bytes = self.config.get("max_mresp_payload_bytes", DEFAULT_MAX_MRESP_MSGS_PAYLOAD_BYTES)
        if self.sync_interval > 0:
            self.sync_timer.start() # Start sync timer if interval is positive


    def process_discovery_request(self, message: Dict, sender_mesh_id: str):
        """Handles a received DISCOVERY_REQ by sending back current status."""
        sender_amcs_id = message.get("from")
        if sender_amcs_id is None:
            logger.warning("Malformed DISCOVERY_REQ: missing 'from' field.")
            return

        logger.info(f"Received DISCOVERY_REQ from Node {sender_amcs_id} ({sender_mesh_id})")
        try:
            response_payload = {
                "cluster_id": self.cluster_id,
                "role": self.node.role.name,
                "controller_amcs_id": self.controller_amcs_id,
                "term": self.election_term # Include current term
            }
            response_msg = self.message_handler.create_message(MSG_TYPE_DISCOVERY_RESP, response_payload)
            self.node.send_amcs_message(response_msg, destination_id_hex=sender_mesh_id)
        except Exception as e:
            logger.exception(f"Error processing DISCOVERY_REQ from {sender_amcs_id}")


    def process_discovery_response(self, message: Dict, sender_mesh_id: str, rssi: Optional[int], snr: Optional[float]):
        """Handles a received DISCOVERY_RESP, updating neighbor info and potentially joining a cluster."""
        sender_amcs_id = message.get("from")
        payload = message.get("p", {})

        # Validate payload
        if not all(k in payload for k in ("role", "controller_amcs_id")) or sender_amcs_id is None: # cluster_id can be None
            logger.warning(f"Malformed DISCOVERY_RESP from {sender_amcs_id}: Missing required fields. Payload: {payload}")
            self.node.stats['malformed_payloads_recv'] += 1
            return

        resp_cluster_id = payload.get("cluster_id") # Can be None
        resp_role_str = payload.get("role")
        resp_controller_id = payload.get("controller_amcs_id") # Can be None if no controller known
        resp_term = payload.get("term", 0) # Get term if available

        try:
            resp_role = self.NodeRole[resp_role_str.upper()] # Be robust to case
        except KeyError:
             logger.warning(f"Received DISCOVERY_RESP from {sender_amcs_id} with invalid role string: {resp_role_str}")
             return

        logger.info(f"Received DISCOVERY_RESP from Node {sender_amcs_id}: Cluster={resp_cluster_id}, Role={resp_role.name}, Controller={resp_controller_id}, Term={resp_term}, RSSI={rssi}")
        self.update_neighbor(sender_amcs_id, sender_mesh_id, resp_role, resp_cluster_id, resp_term, rssi, snr)

        # Join logic (only if DISCOVERING)
        if self.node.role == self.NodeRole.DISCOVERING:
            if resp_role == self.NodeRole.CONTROLLER and resp_cluster_id is not None and resp_controller_id is not None:
                # Found an active controller
                # TODO: Add smarter logic if multiple controllers respond (e.g., strongest RSSI, highest term?)
                # For now, join the first valid one encountered.
                logger.info(f"Node {self.node_id} found potential controller {sender_amcs_id} for Cluster {resp_cluster_id} (Term: {resp_term}). Attempting to join.")
                self.join_cluster(resp_cluster_id, sender_amcs_id, sender_mesh_id, resp_term)
                self.node.discovery_timer.stop() # Stop active discovery probes


    def process_heartbeat(self, message: Dict, sender_mesh_id: str, rssi: Optional[int], snr: Optional[float]):
        """Processes a received HEARTBEAT, updating neighbor/controller status."""
        sender_amcs_id = message.get("from")
        payload = message.get("p", {})

        # Validate payload
        if not all(k in payload for k in ("role", "cluster_id", "term")) or sender_amcs_id is None:
            logger.warning(f"Malformed HEARTBEAT from {sender_amcs_id}: Missing fields. Payload: {payload}")
            self.node.stats['malformed_payloads_recv'] += 1
            return

        hb_role_str = payload["role"]
        hb_cluster_id = payload["cluster_id"] # Can be None
        hb_term = payload.get("term", 0) # Assume term 0 if missing for backward compatibility

        try:
            hb_role = self.NodeRole[hb_role_str.upper()]
        except KeyError:
             logger.warning(f"Received HEARTBEAT from {sender_amcs_id} with invalid role: {hb_role_str}")
             return

        self.update_neighbor(sender_amcs_id, sender_mesh_id, hb_role, hb_cluster_id, hb_term, rssi, snr)

        # If this heartbeat is from our current controller
        if sender_amcs_id == self.controller_amcs_id:
             # logger.debug(f"Heartbeat from current controller {sender_amcs_id} (Term: {hb_term})")
             self.last_controller_heartbeat = time.monotonic()
             self.controller_timeouts_consecutive = 0 # Reset counter

             # Check for term consistency or controller change
             if hb_term > self.election_term:
                  logger.warning(f"Controller {sender_amcs_id} has higher term {hb_term} than our current {self.election_term}. Updating term and re-evaluating.")
                  self.election_term = hb_term # Adopt higher term
                  # If controller's cluster_id changed, or if it's no longer controller, leave.
                  if hb_cluster_id != self.cluster_id or hb_role != self.NodeRole.CONTROLLER:
                       logger.warning(f"Controller's status changed (Cluster: {hb_cluster_id}, Role: {hb_role.name}). Leaving current cluster.")
                       self.leave_cluster()
                       self.start_discovery() # Will re-discover or join election
             elif hb_cluster_id != self.cluster_id:
                  logger.warning(f"Controller {sender_amcs_id}'s heartbeat for cluster {hb_cluster_id}, but we are in {self.cluster_id}. Leaving cluster.")
                  self.leave_cluster()
                  self.start_discovery()


    def update_neighbor(self, amcs_id: int, mesh_id: str, role: 'NodeRole', cluster_id: Optional[int], term: int, rssi: Optional[int], snr: Optional[float]):
         """Updates or adds information about a known neighbor node."""
         if amcs_id == self.node_id: return # Don't track self
         if not isinstance(role, self.NodeRole): return # Invalid role type

         now = time.monotonic()
         self.neighbors[amcs_id] = {
             'mesh_id': mesh_id, 'last_seen': now, 'role': role,
             'cluster_id': cluster_id, 'term': term, 'rssi': rssi, 'snr': snr,
         }
         # logger.debug(f"Updated neighbor {amcs_id}: Role={role.name}, Cluster={cluster_id}, Term={term}")


    def join_cluster(self, cluster_id_to_join: int, controller_id: int, controller_mesh: str, term: int):
        """Sets the node's internal state to join a specific cluster."""
        # Allow joining if DISCOVERING or if joining a higher term controller
        if self.node.role not in [self.NodeRole.DISCOVERING, self.NodeRole.ELECTION] and term <= self.election_term :
             if self.cluster_id == cluster_id_to_join and self.controller_amcs_id == controller_id:
                  # logger.debug(f"Already member of cluster {cluster_id_to_join} with controller {controller_id}.")
                  # Update term if controller announced higher one
                  if term > self.election_term: self.election_term = term
                  self.last_controller_heartbeat = time.monotonic() # Treat as heartbeat
                  return
             logger.warning(f"Attempted to join cluster {cluster_id_to_join} while not DISCOVERING/ELECTION or term not higher. Current: {self.node.role.name}, Term: {self.election_term}")
             return

        logger.info(f"Node {self.node_id} joining Cluster {cluster_id_to_join} with Controller {controller_id} (Mesh: {controller_mesh}, Term: {term})")
        self.cluster_id = cluster_id_to_join
        self.controller_amcs_id = controller_id
        self.controller_mesh_id = controller_mesh
        self.election_term = term # Adopt controller's term
        self.last_controller_heartbeat = time.monotonic()
        self.joined_cluster_time = time.monotonic()
        self.controller_timeouts_consecutive = 0 # Reset
        self.election_active = False # Stop any ongoing election
        self.election_timer.stop()
        self.node.discovery_timer.stop() # Stop discovery probes
        # Role change to MEMBER will occur in Node's main loop


    def leave_cluster(self):
        """Resets cluster information, effectively leaving the current cluster."""
        # ... (Existing logic: Log, reset cluster vars, stop election) ...
        if self.node.role == self.NodeRole.CONTROLLER and self.node.controller_logic:
             self.node.controller_logic.stop_controller_tasks()
        self.cluster_id = None; self.controller_amcs_id = None; self.controller_mesh_id = None
        # Keep election_term, don't reset, as it helps prevent joining older-term clusters.


    def start_discovery(self):
         """Initiates the discovery process by leaving current cluster and starting probes."""
         logger.info(f"Node {self.node_id} (Term: {self.election_term}) starting cluster discovery.")
         self.leave_cluster()
         # Role should transition to DISCOVERING in Node's main loop
         self.node.discovery_timer.reset() # Start/restart discovery timer
         try: # Send initial probe immediately
            disc_req_payload = self.message_handler.create_message(MSG_TYPE_DISCOVERY_REQ)
            self.node.send_amcs_message(disc_req_payload)
            self.node.stats['discovery_req_sent'] += 1
         except Exception as e:
              logger.error(f"Failed to send initial discovery request: {e}")


    def perform_maintenance(self):
        """ Performs periodic tasks for cluster, neighbor, election, and sync. """
        now = time.monotonic()

        # --- Prune old neighbors ---
        expired_neighbors = [nid for nid, data in self.neighbors.items()
                             if (now - data.get('last_seen', 0)) > self.neighbor_timeout_duration]
        if expired_neighbors:
            logger.info(f"Timing out neighbors: {expired_neighbors}")
            for nid in expired_neighbors: del self.neighbors[nid]

        # --- Check Controller Status (if MEMBER) ---
        if self.node.role == self.NodeRole.MEMBER and self.controller_amcs_id:
             # ... (Existing logic for controller timeout and starting election) ...
             # ... (Uses self.controller_timeouts_consecutive) ...
             if (now - self.last_controller_heartbeat) > self.config.get("controller_timeout", 180.0):
                  self.controller_timeouts_consecutive += 1
                  logger.warning(f"Controller {self.controller_amcs_id} timed out! (Consecutive: {self.controller_timeouts_consecutive})")
                  self.leave_cluster()
                  self.start_election() # Try to elect new leader


        # --- Check Election Timeout (if ELECTION) ---
        if self.election_active and self.election_timer.expired():
             logger.warning(f"Election for term {self.election_term} timed out. Restarting election with new term.")
             self.start_election(term=self.election_term + 1) # Increment term

        # --- Initiate Neighbor Sync Periodically ---
        if self.sync_interval > 0 and self.node.role not in [self.NodeRole.INITIALIZING, self.NodeRole.ELECTION]:
             if self.sync_timer.expired():
                  self.initiate_neighbor_sync()
                  self.sync_timer.reset()

        # --- Log Neighbor Status Periodically ---
        if (now - self._last_neighbor_log_time) >= self.neighbor_log_interval:
             self._log_neighbor_status(now)


    def _log_neighbor_status(self, current_time: float):
        """Helper method to log current neighbor status."""
        # ... (Existing logic remains the same) ...


    def determine_current_role(self) -> 'NodeRole':
         """Determines the appropriate role for the node based on current state."""
         # ... (Logic remains the same, using self.NodeRole) ...
         current_node_role = self.node.role
         if current_node_role == self.NodeRole.INITIALIZING: return self.NodeRole.INITIALIZING
         if self.election_active: return self.NodeRole.ELECTION
         if self.cluster_id == self.node_id and self.controller_amcs_id == self.node_id:
             return self.NodeRole.CONTROLLER
         if self.cluster_id is not None and self.controller_amcs_id is not None: # And not self
             return self.NodeRole.MEMBER
         return self.NodeRole.DISCOVERING


    def get_cluster_members(self) -> Set[int]:
         """ Returns the set of AMCS Node IDs of active members in the same cluster. """
         # ... (Existing logic with timeout check remains the same) ...


    # --- Controller Election Logic ---
    def start_election(self, term: Optional[int] = None):
        """Initiates a controller election for a new or specified term."""
        if self.node.role == self.NodeRole.INITIALIZING: return # Cannot start election if not connected

        # If already in an active election for a higher or equal term, don't restart unless forced by higher term
        if self.election_active and term is not None and term <= self.election_term:
             logger.debug(f"Election already active for term {self.election_term}, new request for term {term} ignored.")
             return

        self.election_term = term if term is not None else self.election_term + 1
        self.node.role = self.NodeRole.ELECTION # Change role immediately
        self.election_active = True
        self.voted_in_term = self.election_term # Mark participation
        self.election_candidate_id = self.node_id # Vote for self
        self.votes_received = {self.election_term: {self.node_id: 1}} # Own vote
        self.election_timer.reset() # Start/Restart election timer

        logger.info(f"Node {self.node_id} starting election for Term {self.election_term}. Voting for self.")
        try:
            election_payload = {"term": self.election_term, "candidate_id": self.node_id} # Announce candidacy
            request_msg = self.message_handler.create_message(MSG_TYPE_ELECTION_REQUEST, election_payload)
            self.node.send_amcs_message(request_msg) # Broadcast request
            self.node.stats['election_req_sent'] += 1
        except Exception as e:
             logger.error(f"Failed to send ELECTION_REQUEST for term {self.election_term}: {e}")


    def process_election_request(self, message: Dict, sender_mesh_id: str):
        """Handles an ELECTION_REQUEST message."""
        sender_amcs_id = message.get("from")
        payload = message.get("p", {})
        request_term = payload.get("term")
        candidate_id = payload.get("candidate_id") # Requester is a candidate

        if sender_amcs_id is None or request_term is None or candidate_id is None:
            logger.warning(f"Malformed ELECTION_REQUEST from {sender_mesh_id}: {message}")
            return

        logger.debug(f"Received ELECTION_REQUEST from {sender_amcs_id} (Candidate: {candidate_id}) for Term {request_term}")

        # If their term is higher, update our term and become a follower in that election
        if request_term > self.election_term:
            logger.info(f"Joining election for higher Term {request_term} initiated by {sender_amcs_id}.")
            self.election_term = request_term
            self.node.role = self.NodeRole.ELECTION # Ensure role update
            self.election_active = True
            self.voted_in_term = -1 # Reset vote for new term
            self.election_candidate_id = None
            self.votes_received = {} # Clear old votes
            self.election_timer.reset() # Reset timer for this new higher term election

        # If terms match and we haven't voted yet OR candidate has lower ID (tie-breaker for stability)
        if request_term == self.election_term:
            if not self.election_active: # We weren't in an election, but received a request for our current term
                logger.info(f"Joining ongoing election for Term {self.election_term} due to request from {sender_amcs_id}.")
                self.node.role = self.NodeRole.ELECTION
                self.election_active = True
                self.election_timer.reset() # Start timer if joining

            if self.voted_in_term < self.election_term or \
               (self.election_candidate_id is not None and candidate_id < self.election_candidate_id):
                # Vote for the requesting candidate (or switch vote if their ID is lower)
                logger.info(f"Term {self.election_term}: Voting for candidate {candidate_id} (From {sender_amcs_id}). Previous vote: {self.election_candidate_id}")
                self.voted_in_term = self.election_term
                self.election_candidate_id = candidate_id

                try:
                    vote_payload = {"term": self.election_term, "vote_for": candidate_id}
                    vote_msg = self.message_handler.create_message(MSG_TYPE_ELECTION_VOTE, vote_payload)
                    # Send vote broadcast so others also see vote counts
                    self.node.send_amcs_message(vote_msg)
                    self.node.stats['election_votes_sent'] += 1
                except Exception as e:
                     logger.error(f"Failed to send ELECTION_VOTE for term {self.election_term}: {e}")
            else:
                 logger.debug(f"Term {self.election_term}: Already voted for {self.election_candidate_id} or candidate ID {candidate_id} not preferred. Ignoring ELECTION_REQUEST from {sender_amcs_id}.")
        # else: request_term < self.election_term, ignore.


    def process_election_vote(self, message: Dict, sender_mesh_id: str):
        """Processes a received ELECTION_VOTE message."""
        sender_amcs_id = message.get("from") # Voter
        payload = message.get("p", {})
        vote_term = payload.get("term")
        voted_for_candidate = payload.get("vote_for") # Candidate ID voted for

        if sender_amcs_id is None or vote_term is None or voted_for_candidate is None:
            logger.warning(f"Malformed ELECTION_VOTE from {sender_mesh_id}: {message}")
            return

        logger.debug(f"Received VOTE from {sender_amcs_id} for candidate {voted_for_candidate} in Term {vote_term}")

        # Ignore votes for terms older than current election term or if not in election
        if vote_term < self.election_term or not self.election_active:
            logger.debug(f"Ignoring VOTE for older term {vote_term} or not in election (current term: {self.election_term}, active: {self.election_active})")
            return
        # If vote is for a future term, this is unusual; ELECTION_REQUEST should handle term updates.
        if vote_term > self.election_term:
            logger.warning(f"Received VOTE for future term {vote_term}. Updating term and resetting election state.")
            self.election_term = vote_term
            self.election_active = True
            self.node.role = self.NodeRole.ELECTION
            self.voted_in_term = -1; self.election_candidate_id = None; self.votes_received = {}
            self.election_timer.reset()
            return # Don't process this vote now, wait for proper EREQ or new votes in this term

        # Process vote if for the current election term
        if vote_term == self.election_term:
            # Initialize vote count dict for the term if not present
            if self.election_term not in self.votes_received:
                 self.votes_received[self.election_term] = {}
            term_votes_map = self.votes_received[self.election_term]

            # Add vote (typically, one vote per node, but a simple count here)
            # TODO: Ensure a node (sender_amcs_id) can only vote once per term effectively.
            # Current logic just sums votes for a candidate. If node itself is tracking voted_in_term,
            # it shouldn't send multiple votes. Here we just count what's received.
            term_votes_map[voted_for_candidate] = term_votes_map.get(voted_for_candidate, 0) + 1
            logger.debug(f"Term {self.election_term} Vote Tally: {term_votes_map}")

            # Check for winner: candidate needs majority of potential voters.
            # Potential voters: self + active neighbors also in ELECTION or DISCOVERING state.
            active_potential_voters = {
                nid for nid, data in self.neighbors.items()
                if (time.monotonic() - data.get('last_seen', 0)) <= self.neighbor_timeout_duration and \
                   data.get('term', -1) >= self.election_term and # Consider only nodes aware of current/recent terms
                   data.get('role') in [self.NodeRole.DISCOVERING, self.NodeRole.ELECTION]
            }
            active_potential_voters.add(self.node_id) # Include self
            num_potential_voters = len(active_potential_voters)

            if num_potential_voters == 0: num_potential_voters = 1 # Avoid division by zero if isolated
            majority_threshold = (num_potential_voters // 2) + 1
            logger.debug(f"Term {self.election_term}: Potential voters in election: {num_potential_voters}. Majority needed: {majority_threshold}.")

            # Did the candidate just voted for win?
            candidate_receiving_vote = voted_for_candidate
            current_candidate_votes = term_votes_map.get(candidate_receiving_vote, 0)

            if current_candidate_votes >= majority_threshold:
                logger.info(f"ELECTION WINNER for Term {self.election_term}: Node {candidate_receiving_vote} "
                            f"with {current_candidate_votes}/{num_potential_voters} votes.")
                self.election_active = False # Election concluded
                self.election_timer.stop()

                if candidate_receiving_vote == self.node_id: # This node won
                    self.become_controller()
                    # Announce victory
                    try:
                        win_payload = {"term": self.election_term, "winner_id": self.node_id}
                        win_msg = self.message_handler.create_message(MSG_TYPE_ELECTION_WINNER, win_payload)
                        self.node.send_amcs_message(win_msg) # Broadcast win
                        self.node.stats['election_wins_announced'] += 1
                    except Exception as e:
                         logger.error(f"Failed to send ELECTION_WINNER message: {e}")
                else: # Another node won
                    logger.info(f"Node {candidate_receiving_vote} won election. Waiting for their announcement/heartbeat to join.")
                    # Attempt to join winner's cluster if known.
                    # This state might be short-lived if winner's EWIN arrives quickly.
                    winner_data = self.neighbors.get(candidate_receiving_vote)
                    if winner_data and winner_data.get('mesh_id'):
                         self.join_cluster(candidate_receiving_vote, candidate_receiving_vote, winner_data['mesh_id'], self.election_term)
                    else:
                         logger.warning(f"Winner {candidate_receiving_vote}'s mesh ID not in neighbors. Will rely on their EWIN or discovery.")
                         # Stay in ELECTION or transition to DISCOVERING via determine_current_role
                         self.start_discovery() # Fallback to re-discover

            # else: No winner yet, continue election

    def process_election_winner(self, message: Dict, sender_mesh_id: str):
         """Handles an ELECTION_WINNER announcement from the elected controller."""
         sender_amcs_id = message.get("from")
         payload = message.get("p", {})
         win_term = payload.get("term")
         winner_id = payload.get("winner_id")

         if sender_amcs_id is None or win_term is None or winner_id is None or \
            not isinstance(win_term, int) or not isinstance(winner_id, int): # Basic validation
            logger.warning(f"Malformed ELECTION_WINNER from {sender_mesh_id}: {message}")
            return

         logger.info(f"Received ELECTION_WINNER announcement for Term {win_term}. Winner: {winner_id} (Announced by: {sender_amcs_id})")

         # Winner must be the sender of the announcement
         if sender_amcs_id != winner_id:
              logger.warning(f"ELECTION_WINNER sender {sender_amcs_id} mismatch with announced winner {winner_id}. Ignoring.")
              return

         # If announcement is for an older term than our current election term, ignore
         if win_term < self.election_term:
              logger.debug(f"Ignoring ELECTION_WINNER for older term {win_term} (current term: {self.election_term})")
              return

         # If this node was controller but receives a higher term winner, step down
         if self.node.role == self.NodeRole.CONTROLLER and win_term > self.election_term:
              logger.warning(f"Stepping down as controller due to higher term {win_term} ELECTION_WINNER ({winner_id}).")
              self.leave_cluster()
              # Fall through to join logic

         # If this is for current or future term, and we are not the winner:
         if win_term >= self.election_term and winner_id != self.node_id:
              logger.info(f"Acknowledging new controller {winner_id} for Term {win_term}. Attempting to join cluster.")
              self.election_active = False # Stop any local election activity
              self.election_timer.stop()
              # self.election_term = win_term # Updated in join_cluster
              self.join_cluster(winner_id, winner_id, sender_mesh_id, win_term) # Cluster ID = Controller ID

         # If we are the winner and this is our own announcement, it's fine (idempotent)
         elif winner_id == self.node_id and win_term == self.election_term:
              logger.debug("Received own ELECTION_WINNER announcement. Already controller.")
              # Ensure controller state is set
              if self.node.role != self.NodeRole.CONTROLLER:
                   self.become_controller() # Redundant if already called, but safe


    def become_controller(self):
        """Sets the necessary state variables when this node wins an election and becomes the controller."""
        if self.node.role == self.NodeRole.INITIALIZING:
             logger.error("Cannot become controller while in INITIALIZING state.")
             return

        # Use own node_id as the cluster_id when becoming controller
        new_cluster_id = self.node_id
        logger.info(f"Node {self.node_id} assuming CONTROLLER role for Cluster {new_cluster_id} in Term {self.election_term}.")

        self.cluster_id = new_cluster_id
        self.controller_amcs_id = self.node_id
        # Get own mesh ID from network interface (must be connected)
        node_info = self.node.network.get_node_info() if self.node.network else None
        if node_info and node_info.get('node_id_hex'):
            self.controller_mesh_id = node_info['node_id_hex']
        else:
             logger.error(f"CRITICAL: Node {self.node_id} cannot become controller: Failed to get own mesh ID.")
             # This is a bad state, try to recover by re-discovering
             self.leave_cluster()
             self.start_discovery()
             return

        self.last_controller_heartbeat = time.monotonic() # Start own "heartbeat" timing
        self.joined_cluster_time = time.monotonic()
        self.controller_timeouts_consecutive = 0 # Reset this counter
        self.election_active = False
        self.election_timer.stop()
        # Node's main loop will pick up the role change and initialize ControllerLogic
        # Ensure discovery is stopped if becoming controller
        self.node.discovery_timer.stop()


    # --- Neighbor Synchronization Methods (Implemented in previous step) ---
    # (initiate_neighbor_sync, process_sync_request, process_sync_info,
    #  process_missing_message_request with chunking, process_missing_message_response)
    # ...
