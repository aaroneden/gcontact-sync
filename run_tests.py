#!/usr/bin/env python3
"""Test runner script for running pytest programmatically."""

import os
import site
import sys

# Enable user site-packages
site.ENABLE_USER_SITE = True

# Add user site-packages to path
user_site = os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages")
if user_site not in sys.path:
    sys.path.insert(0, user_site)

import pytest

# Run pytest with coverage
sys.exit(pytest.main(["tests/", "-v", "--cov=gcontact_sync"]))
