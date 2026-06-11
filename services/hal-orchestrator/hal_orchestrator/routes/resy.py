"""Descoped: Resy is read-only (find a table + hand the user a booking link).

The per-user account connect / booking flow was intentionally removed — HAL does
NOT book on anyone's behalf, so there's no connect web form. See tools/resy.py.
This module is intentionally empty and not wired into the app.
"""
