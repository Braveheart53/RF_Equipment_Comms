# -*- coding: utf-8 -*-
"""
=============================================================================
# %% Header Info
--------
#!/usr/bin/env python3
Created on %(date)s

# %%% Author Information
@author: William W. Wallace
Author Email: wwallace@nrao.edu
Author Secondary Email: naval.antennas@gmail.com
Author Business Phone: +1 (304) 456-2216


# %%% Revisions
--------
Utilizing Semantic Schema as External Release.Internal Release.Working version

# %%%% 0.0.1: Script to run in consol description
Date:
# %%%%% Function Descriptions
        main: main script body
        select_file: utilzing module os, select multiple files for processing

# %%%%% Variable Descriptions
    Define all utilized variables
        file_path: path(s) to selected files for processing

# %%%%% More Info

# %%%% 0.0.2: NaN
Date:
# %%%%% Function Descriptions
        main: main script body
        select_file: utilzing module os, select multiple files for processing
    More Info:
# %%%%% Variable Descriptions
    Define all utilized variables
        file_path: path(s) to selected files for processing
# %%%%% More Info
=============================================================================
"""

"""
Installation script for Agilent/Keysight Instrument Test Suite
Installs required dependencies and sets up the environment.
"""
# %% Module Imports
import subprocess
import sys
import os

# %% Functions Defs
def install_requirements():
    """Install required Python packages."""

    requirements = [
        "qtpy>=2.0.0",
        "pyside6>=6.0.0",  # Qt backend
        "pyvisa>=1.11.0",
        "pyvisa-py>=0.5.0"  # Pure Python VISA implementation
    ]

    print("Installing required packages...")
    for package in requirements:
        try:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            print(f"✓ {package} installed successfully")
        except subprocess.CalledProcessError:
            print(f"✗ Failed to install {package}")
            return False

    return True

def create_example_config():
    """Create example configuration files."""

    config_content = """# Agilent/Keysight Instrument Test Configuration

# Common VISA addresses for testing
EXAMPLE_ADDRESSES = [
    "USB0::0x2A8D::0x1401::MY12345678::INSTR",  # USB connection
    "GPIB0::22::INSTR",                          # GPIB connection
    "TCPIP0::192.168.1.100::INSTR",              # Ethernet connection
    "ASRL1::INSTR"                               # Serial connection
]

# Test timeout settings (seconds)
DEFAULT_TIMEOUT = 5
LONG_TEST_TIMEOUT = 30

# Logging configuration
LOG_LEVEL = "INFO"
LOG_FILE = "instrument_test.log"

# Test parameters
RESPONSE_TIME_THRESHOLD = 1.0  # seconds
COMMUNICATION_SUCCESS_RATE = 0.9  # 90%
SCPI_COMPLIANCE_RATE = 0.8  # 80%
"""

    try:
        with open("test_config.py", "w") as f:
            f.write(config_content)
        print("✓ Created test_config.py")
    except Exception as e:
        print(f"✗ Failed to create configuration file: {e}")

# %% Main
def main():
    """Main installation function."""
    print("Agilent/Keysight Instrument Test Suite Installer")
    print("=" * 50)

    # Check Python version
    if sys.version_info < (3, 7):
        print("✗ Python 3.7 or higher required")
        return 1

    print(f"✓ Python {sys.version.split()[0]} detected")

    # Install requirements
    if not install_requirements():
        print("Installation failed!")
        return 1

    # Create example configuration
    create_example_config()

    print("\n" + "=" * 50)
    print("Installation completed successfully!")
    print("\nTo run the application:")
    print("  python instrument_test_gui.py")
    print("\nMake sure you have:")
    print("  - VISA drivers installed (NI-VISA or Keysight IO Libraries)")
    print("  - Instruments connected via USB, GPIB, or Ethernet")
    print("  - Proper VISA addresses configured")

    return 0

if __name__ == "__main__":
    sys.exit(main())
