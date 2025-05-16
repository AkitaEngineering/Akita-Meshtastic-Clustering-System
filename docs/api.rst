========
API Docs
========

This section is intended for auto-generated API documentation from the source code docstrings.
To generate this, you would typically use ``sphinx-apidoc`` to create reStructuredText files
from your Python modules, and then include those files here or reference them.

Example (you might run this from the ``docs/`` directory):
``sphinx-apidoc -o . ../src/akita_meshtastic_clustering``

Then, you can list the modules in the toctree or directly use automodule directives.

.. HINT::
   After running ``sphinx-apidoc``, you might get files like ``akita_meshtastic_clustering.rst``
   which you can then include: ``.. include:: akita_meshtastic_clustering.rst``
   Or, list modules individually:

Available Modules
-----------------

.. toctree::
   :maxdepth: 1

   AMCS Core Node <api_generated/akita_meshtastic_clustering.node>
   Cluster Management <api_generated/akita_meshtastic_clustering.cluster>
   Controller Logic <api_generated/akita_meshtastic_clustering.controller>
   Messaging & Storage <api_generated/akita_meshtastic_clustering.messaging>
   Network Interface <api_generated/akita_meshtastic_clustering.network>
   Configuration <api_generated/akita_meshtastic_clustering.config>
   Utilities <api_generated/akita_meshtastic_clustering.utils>
   Power Management <api_generated/akita_meshtastic_clustering.power>
   Exceptions <api_generated/akita_meshtastic_clustering.exceptions>

.. note::
   You will need to run ``sphinx-apidoc -o api_generated ../src/akita_meshtastic_clustering`` from the ``docs``
   directory to generate the ``*.rst`` files for the ``api_generated`` folder, then build the Sphinx documentation.
   Ensure ``sphinx.ext.autodoc`` and ``sphinx.ext.napoleon`` are in your ``conf.py`` extensions list.

Individual Module Documentation (Example Structure)
---------------------------------------------------

Node Module
~~~~~~~~~~~
.. automodule:: akita_meshtastic_clustering.node
   :members:
   :undoc-members:
   :show-inheritance:

Cluster Module
~~~~~~~~~~~~~~
.. automodule:: akita_meshtastic_clustering.cluster
   :members:
   :undoc-members:
   :show-inheritance:

Controller Module
~~~~~~~~~~~~~~~~~
.. automodule:: akita_meshtastic_clustering.controller
   :members:
   :undoc-members:
   :show-inheritance:

Messaging Module
~~~~~~~~~~~~~~~~
.. automodule:: akita_meshtastic_clustering.messaging
   :members:
   :undoc-members:
   :show-inheritance:

Network Module
~~~~~~~~~~~~~~
.. automodule:: akita_meshtastic_clustering.network
   :members:
   :undoc-members:
   :show-inheritance:

*(Add other modules as needed: config, utils, power, exceptions)*
