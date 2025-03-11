## Explanation of Values:

* **`node_id`**:
    * This is a unique numerical identifier for your Meshtastic node. Choose a number that's not likely to be used by other nodes in your network.
    * Example: `4567`
* **`heartbeat_interval`**:
    * This sets the frequency (in seconds) at which your node sends out "heartbeat" messages to indicate its presence to other cluster members.
    * A shorter interval means more frequent updates, but also more network traffic and power consumption.
    * Example: `12` (seconds)
* **`ack_timeout`**:
    * This specifies the maximum time (in seconds) a node will wait for an acknowledgment (ACK) message before considering a message lost.
    * Example: `6` (seconds)
* **`rebroadcast_delay`**:
    * This is the delay (in seconds) the controller will wait before rebroadcasting a message to a node that has not responded with an ACK.
    * Example: `3` (seconds)
* **`message_retention`**:
    * This determines the maximum number of messages that the node will store in its message queue.
    * A higher number allows for more reliable delivery, but also consumes more memory.
    * Example: `25`
* **`cluster_discovery_interval`**:
    * This is the interval in seconds that the node will send out cluster discovery messages.
    * Example: `45` (seconds)
* **`sleep_interval`**:
    * This is the interval in seconds that the node will enter a low power sleep state.
    * Example: `90` (seconds)

## How to Use:

1.  **Create the File**: Create a new file named `cluster_config.json` in the same directory as your `cluster_node.py` script.
2.  **Paste the Content**: Copy and paste the JSON code above into the file.
3.  **Customize**: Modify the values to suit your specific Meshtastic network and requirements.
4.  **Save**: Save the file.

Remember that if you omit the `cluster_config.json` file, the program will use default configuration values.
