#!/usr/bin/env python3
"""Generate a SHA-256 password hash for use in .streamlit/secrets.toml.

Usage:
    python hash_password.py
    python hash_password.py mypassword
"""
import hashlib, sys, getpass

if len(sys.argv) > 1:
    pw = sys.argv[1]
else:
    pw = getpass.getpass("Enter password to hash: ")

print(f"sha256:{hashlib.sha256(pw.encode()).hexdigest()}")
