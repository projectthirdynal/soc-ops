#!/usr/bin/env python3
"""Admin utility — generate a licence key for a given machine ID.

Usage:
    python keygen.py <MACHINE_ID>

The machine ID is displayed on the trial-expired lock screen of each client.
The generated key is valid only for that specific machine.
"""

import sys

# Re-use the same signing logic from the app
from app.core.trial import generate_licence_key


def main() -> None:
    if len(sys.argv) != 2 or len(sys.argv[1]) < 8:
        print("Usage: python keygen.py <MACHINE_ID>")
        print("  MACHINE_ID is shown on the client's lock screen.")
        sys.exit(1)

    machine_id = sys.argv[1].strip().upper()
    key = generate_licence_key(machine_id)

    print()
    print(f"  Machine ID : {machine_id}")
    print(f"  Licence Key: {key}")
    print()
    print("  Give this key to the user. They paste it on the lock screen to activate.")


if __name__ == "__main__":
    main()
