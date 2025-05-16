# docs/conf.py
# Configuration file for the Sphinx documentation builder.

import os
import sys
# Point to project source code (relative to docs directory)
sys.path.insert(0, os.path.abspath('../src'))

# -- Project information -----------------------------------------------------
project = 'Akita Meshtastic Clustering System'
copyright = '2025, Akita Engineering' # Updated year based on current date context
author = 'Akita Engineering'
release = '0.4.0' # Update with current version

# -- General configuration ---------------------------------------------------
extensions = [
    'sphinx.ext.autodoc',  # Include documentation from docstrings
    'sphinx.ext.napoleon', # Support Google and NumPy style docstrings
    'sphinx.ext.intersphinx', # Link to other projects' documentation
    'sphinx.ext.viewcode', # Add links to source code
]
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# -- Options for HTML output -------------------------------------------------
# Use a common theme, ensure it's installed: pip install sphinx_rtd_theme
html_theme = 'sphinx_rtd_theme'
# html_static_path = ['_static'] # If you have custom static files

# -- Options for autodoc ----------------------------------------------------
autodoc_member_order = 'bysource'

# -- Options for intersphinx ------------------------------------------------
intersphinx_mapping = {'python': ('https://docs.python.org/3', None)}
