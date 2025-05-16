# Copyright (c) 2025 Akita Engineering <https://www.akitaengineering.com>
# SPDX-License-Identifier: GPL-3.0-or-later

class AMCSException(Exception):
    """Base exception for AMCS specific errors."""
    pass

class ConfigurationError(AMCSException):
    """Error related to configuration loading or validation."""
    pass

class NetworkError(AMCSException):
    """Error related to network communication (Meshtastic interface)."""
    pass

class MessageError(AMCSException):
    """Error related to message creation, parsing, or handling."""
    pass

class StateError(AMCSException):
    """Error related to invalid node state transitions or operations in current state."""
    pass

class ElectionError(AMCSException):
    """Error related to the controller election process."""
    pass
