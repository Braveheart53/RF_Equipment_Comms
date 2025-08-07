# -*- coding: utf-8 -*-

"""
#!/usr/bin/env python3
=============================================================================
# %% Header Info
--------

Created on 2025-08-07

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
Agilent/Keysight Instrument Test GUI Application
Using QtPy and PyVISA for comprehensive device testing

This application provides automated testing capabilities for Agilent and
Keysight instruments
with visual status indicators showing pass/fail results for each test.
"""
# %% Import General Modules
import sys
import time
import logging
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from datetime import datetime

# %%% Import QtPy components
try:
    from qtpy.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QGridLayout, QPushButton, QLabel,
                               QTextEdit, QComboBox, QProgressBar, QGroupBox,
                               QMessageBox, QFrame, QScrollArea, QTabWidget)
    from qtpy.QtCore import QThread, Signal, QTimer, Qt
    from qtpy.QtGui import QFont, QPalette, QColor
except ImportError:
    print("Error: QtPy not installed. Install with: pip install qtpy pyside6")
    sys.exit(1)

# %%% Import PyVISA
try:
    import pyvisa
    from pyvisa.errors import VisaIOError, InvalidBinaryFormat
except ImportError:
    print("Error: PyVISA not installed. Install with: pip install pyvisa")
    sys.exit(1)

# %% Class and Function Space
@dataclass
class TestResult:
    """Data class to store test results."""
    test_name: str
    passed: bool
    message: str
    execution_time: float
    timestamp: datetime


class InstrumentTester(QThread):
    """
    Worker thread for instrument testing operations.
    Performs tests asynchronously to keep GUI responsive.
    """

    # Signals for communication with main thread
    test_completed = Signal(TestResult)
    test_started = Signal(str)
    progress_updated = Signal(int)
    log_message = Signal(str)

    def __init__(self, resource_address: str):
        super().__init__()
        self.resource_address = resource_address
        self.instrument = None
        self.rm = None
        self.tests_to_run = []

    def add_test(self, test_name: str):
        """Add a test to the queue."""
        self.tests_to_run.append(test_name)

    def run(self):
        """Execute all queued tests."""
        if not self.tests_to_run:
            return

        try:
            # Initialize VISA resource manager
            self.rm = pyvisa.ResourceManager()

            # Connect to instrument
            self.instrument = self.rm.open_resource(self.resource_address)
            self.instrument.timeout = 5000  # 5 second timeout

            total_tests = len(self.tests_to_run)

            for i, test_name in enumerate(self.tests_to_run):
                self.test_started.emit(test_name)
                result = self._execute_test(test_name)
                self.test_completed.emit(result)

                # Update progress
                progress = int((i + 1) * 100 / total_tests)
                self.progress_updated.emit(progress)

                time.sleep(0.1)  # Brief pause between tests

        except Exception as e:
            error_result = TestResult(
                test_name="Connection",
                passed=False,
                message=f"Failed to connect: {str(e)}",
                execution_time=0.0,
                timestamp=datetime.now()
            )
            self.test_completed.emit(error_result)

        finally:
            self._cleanup()

    def _execute_test(self, test_name: str) -> TestResult:
        """Execute a specific test and return the result."""
        start_time = time.time()

        try:
            if test_name == "Connection Test":
                return self._test_connection()
            elif test_name == "Identification":
                return self._test_identification()
            elif test_name == "Self Test":
                return self._test_self_test()
            elif test_name == "Reset Command":
                return self._test_reset()
            elif test_name == "Error Status":
                return self._test_error_status()
            elif test_name == "Status Registers":
                return self._test_status_registers()
            elif test_name == "Operation Complete":
                return self._test_operation_complete()
            elif test_name == "Response Time":
                return self._test_response_time()
            elif test_name == "Communication Stability":
                return self._test_communication_stability()
            elif test_name == "SCPI Compliance":
                return self._test_scpi_compliance()
            else:
                return TestResult(
                    test_name=test_name,
                    passed=False,
                    message="Unknown test",
                    execution_time=time.time() - start_time,
                    timestamp=datetime.now()
                )

        except Exception as e:
            return TestResult(
                test_name=test_name,
                passed=False,
                message=f"Test failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _test_connection(self) -> TestResult:
        """Test basic connection to instrument."""
        start_time = time.time()
        try:
            # Try a simple query
            response = self.instrument.query("*IDN?")
            passed = len(response.strip()) > 0
            message = f"Connected successfully. Response: {response[:50]}..." if passed else "No response"

            return TestResult(
                test_name="Connection Test",
                passed=passed,
                message=message,
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            return TestResult(
                test_name="Connection Test",
                passed=False,
                message=f"Connection failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _test_identification(self) -> TestResult:
        """Test instrument identification query."""
        start_time = time.time()
        try:
            idn_response = self.instrument.query("*IDN?").strip()

            # Check if response contains expected Agilent/Keysight identifiers
            is_agilent_keysight = any(brand.lower() in idn_response.lower()
                                    for brand in ["agilent", "keysight", "hewlett-packard", "hp"])

            message = f"ID: {idn_response}"
            if not is_agilent_keysight:
                message += " (Warning: Not recognized as Agilent/Keysight device)"

            return TestResult(
                test_name="Identification",
                passed=len(idn_response) > 0,
                message=message,
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            return TestResult(
                test_name="Identification",
                passed=False,
                message=f"Failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _test_self_test(self) -> TestResult:
        """Test instrument self-test capability."""
        start_time = time.time()
        try:
            # Send self-test command and get result
            self.instrument.write("*TST")
            time.sleep(1)  # Wait for self-test to complete

            # Query the result
            result = self.instrument.query("*TST?").strip()

            # Result should be "0" for pass
            passed = result == "0"
            message = f"Self-test result: {result} ({'PASS' if passed else 'FAIL'})"

            return TestResult(
                test_name="Self Test",
                passed=passed,
                message=message,
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            return TestResult(
                test_name="Self Test",
                passed=False,
                message=f"Failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _test_reset(self) -> TestResult:
        """Test instrument reset command."""
        start_time = time.time()
        try:
            # Send reset command
            self.instrument.write("*RST")
            time.sleep(2)  # Wait for reset to complete

            # Verify instrument is responsive after reset
            response = self.instrument.query("*IDN?").strip()
            passed = len(response) > 0

            message = f"Reset {'successful' if passed else 'failed'}"

            return TestResult(
                test_name="Reset Command",
                passed=passed,
                message=message,
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            return TestResult(
                test_name="Reset Command",
                passed=False,
                message=f"Failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _test_error_status(self) -> TestResult:
        """Test error status checking."""
        start_time = time.time()
        try:
            # Clear any existing errors
            self.instrument.write("*CLS")

            # Check system error queue
            errors = []
            for _ in range(10):  # Check up to 10 errors
                try:
                    error = self.instrument.query("SYST:ERR?").strip()
                    if error.startswith("0,") or error.startswith("+0,"):
                        break  # No more errors
                    errors.append(error)
                except:
                    break

            passed = len(errors) == 0
            message = f"No errors found" if passed else f"Errors: {'; '.join(errors[:3])}"

            return TestResult(
                test_name="Error Status",
                passed=passed,
                message=message,
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            return TestResult(
                test_name="Error Status",
                passed=False,
                message=f"Failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _test_status_registers(self) -> TestResult:
        """Test status register queries."""
        start_time = time.time()
        try:
            # Query various status registers
            stb = self.instrument.query("*STB?").strip()
            esr = self.instrument.query("*ESR?").strip()

            passed = True
            message = f"STB: {stb}, ESR: {esr}"

            return TestResult(
                test_name="Status Registers",
                passed=passed,
                message=message,
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            return TestResult(
                test_name="Status Registers",
                passed=False,
                message=f"Failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _test_operation_complete(self) -> TestResult:
        """Test operation complete functionality."""
        start_time = time.time()
        try:
            # Send operation complete command
            self.instrument.write("*OPC")

            # Query operation complete status
            opc_result = self.instrument.query("*OPC?").strip()

            passed = opc_result == "1"
            message = f"OPC result: {opc_result}"

            return TestResult(
                test_name="Operation Complete",
                passed=passed,
                message=message,
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            return TestResult(
                test_name="Operation Complete",
                passed=False,
                message=f"Failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _test_response_time(self) -> TestResult:
        """Test instrument response time."""
        start_time = time.time()
        try:
            response_times = []

            # Perform multiple queries and measure response time
            for _ in range(5):
                query_start = time.time()
                self.instrument.query("*IDN?")
                query_time = time.time() - query_start
                response_times.append(query_time)

            avg_response_time = sum(response_times) / len(response_times)
            max_response_time = max(response_times)

            # Consider pass if average response time is under 1 second
            passed = avg_response_time < 1.0
            message = f"Avg: {avg_response_time:.3f}s, Max: {max_response_time:.3f}s"

            return TestResult(
                test_name="Response Time",
                passed=passed,
                message=message,
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            return TestResult(
                test_name="Response Time",
                passed=False,
                message=f"Failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _test_communication_stability(self) -> TestResult:
        """Test communication stability with multiple commands."""
        start_time = time.time()
        try:
            successful_commands = 0
            total_commands = 10

            commands = ["*IDN?", "*STB?", "*ESR?", "*OPC?"]

            for i in range(total_commands):
                try:
                    cmd = commands[i % len(commands)]
                    response = self.instrument.query(cmd)
                    if response.strip():
                        successful_commands += 1
                except:
                    pass
                time.sleep(0.1)

            success_rate = successful_commands / total_commands
            passed = success_rate >= 0.9  # 90% success rate required

            message = f"Success rate: {success_rate:.1%} ({successful_commands}/{total_commands})"

            return TestResult(
                test_name="Communication Stability",
                passed=passed,
                message=message,
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            return TestResult(
                test_name="Communication Stability",
                passed=False,
                message=f"Failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _test_scpi_compliance(self) -> TestResult:
        """Test basic SCPI compliance."""
        start_time = time.time()
        try:
            compliant_commands = 0
            total_commands = 0

            # Test mandatory SCPI commands
            mandatory_commands = ["*IDN?", "*RST", "*CLS", "*ESR?", "*STB?", "*OPC?"]

            for cmd in mandatory_commands:
                total_commands += 1
                try:
                    if cmd.endswith("?"):
                        response = self.instrument.query(cmd)
                        if response.strip():
                            compliant_commands += 1
                    else:
                        self.instrument.write(cmd)
                        compliant_commands += 1
                        time.sleep(0.5)
                except:
                    pass

            compliance_rate = compliant_commands / total_commands
            passed = compliance_rate >= 0.8  # 80% compliance required

            message = f"SCPI compliance: {compliance_rate:.1%} ({compliant_commands}/{total_commands})"

            return TestResult(
                test_name="SCPI Compliance",
                passed=passed,
                message=message,
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )
        except Exception as e:
            return TestResult(
                test_name="SCPI Compliance",
                passed=False,
                message=f"Failed: {str(e)}",
                execution_time=time.time() - start_time,
                timestamp=datetime.now()
            )

    def _cleanup(self):
        """Clean up resources."""
        try:
            if self.instrument:
                self.instrument.close()
            if self.rm:
                self.rm.close()
        except:
            pass


class TestButton(QPushButton):
    """
    Custom test button with status indicator.
    Changes color based on test results (green=pass, red=fail, gray=not run).
    """

    def __init__(self, test_name: str):
        super().__init__(test_name)
        self.test_name = test_name
        self.setMinimumHeight(40)
        self.setStyleSheet(self._get_style("idle"))

    def set_status(self, status: str):
        """Set the button status and update appearance."""
        self.setStyleSheet(self._get_style(status))

    def _get_style(self, status: str) -> str:
        """Get stylesheet for the given status."""
        base_style = """
            QPushButton {
                border: 2px solid;
                border-radius: 8px;
                padding: 8px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                opacity: 0.8;
            }
            QPushButton:pressed {
                border-width: 3px;
            }
        """

        if status == "pass":
            return base_style + """
                QPushButton {
                    background-color: #4CAF50;
                    border-color: #45a049;
                    color: white;
                }
            """
        elif status == "fail":
            return base_style + """
                QPushButton {
                    background-color: #f44336;
                    border-color: #da190b;
                    color: white;
                }
            """
        elif status == "running":
            return base_style + """
                QPushButton {
                    background-color: #ff9800;
                    border-color: #f57c00;
                    color: white;
                }
            """
        else:  # idle
            return base_style + """
                QPushButton {
                    background-color: #e0e0e0;
                    border-color: #bdbdbd;
                    color: black;
                }
            """

#
class InstrumentTestGUI(QMainWindow):
    """
    Main GUI window for the instrument testing application.
    Provides comprehensive testing interface with visual feedback.
    """

    def __init__(self):
        super().__init__()
        self.test_results = {}
        self.test_buttons = {}
        self.tester = None

        self.init_ui()
        self.setup_logging()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Agilent/Keysight Instrument Test Suite")
        self.setMinimumSize(1000, 700)

        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Create header
        header_layout = self._create_header()
        main_layout.addLayout(header_layout)

        # Create main content with tabs
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)

        # Test Control Tab
        test_tab = self._create_test_tab()
        tab_widget.addTab(test_tab, "Tests")

        # Results Tab
        results_tab = self._create_results_tab()
        tab_widget.addTab(results_tab, "Results")

        # Log Tab
        log_tab = self._create_log_tab()
        tab_widget.addTab(log_tab, "Logs")

        # Status bar
        self.statusBar().showMessage("Ready")

    def _create_header(self) -> QHBoxLayout:
        """Create the header section with connection controls."""
        layout = QHBoxLayout()

        # Title
        title = QLabel("Instrument Test Suite")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #2c3e50;")
        layout.addWidget(title)

        layout.addStretch()

        # Connection controls
        layout.addWidget(QLabel("VISA Address:"))

        self.address_combo = QComboBox()
        self.address_combo.setEditable(True)
        self.address_combo.setMinimumWidth(200)
        self.address_combo.addItems([
            "USB0::0x2A8D::0x1401::MY12345678::INSTR",
            "GPIB0::22::INSTR",
            "TCPIP0::192.168.1.100::INSTR",
            "ASRL1::INSTR"
        ])
        layout.addWidget(self.address_combo)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_instruments)
        layout.addWidget(self.refresh_btn)

        return layout

    def _create_test_tab(self) -> QWidget:
        """Create the test control tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Test controls
        controls_layout = QHBoxLayout()

        self.run_all_btn = QPushButton("Run All Tests")
        self.run_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.run_all_btn.clicked.connect(self.run_all_tests)
        controls_layout.addWidget(self.run_all_btn)

        self.stop_btn = QPushButton("Stop Tests")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_tests)
        controls_layout.addWidget(self.stop_btn)

        controls_layout.addStretch()

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        controls_layout.addWidget(self.progress_bar)

        layout.addLayout(controls_layout)

        # Test groups
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # Connection Tests Group
        conn_group = QGroupBox("Connection Tests")
        conn_layout = QGridLayout(conn_group)

        connection_tests = ["Connection Test", "Identification"]
        for i, test in enumerate(connection_tests):
            btn = TestButton(test)
            btn.clicked.connect(lambda checked, t=test: self.run_single_test(t))
            self.test_buttons[test] = btn
            conn_layout.addWidget(btn, i // 2, i % 2)

        scroll_layout.addWidget(conn_group)

        # Status Tests Group
        status_group = QGroupBox("Status Tests")
        status_layout = QGridLayout(status_group)

        status_tests = ["Self Test", "Error Status", "Status Registers", "Operation Complete"]
        for i, test in enumerate(status_tests):
            btn = TestButton(test)
            btn.clicked.connect(lambda checked, t=test: self.run_single_test(t))
            self.test_buttons[test] = btn
            status_layout.addWidget(btn, i // 2, i % 2)

        scroll_layout.addWidget(status_group)

        # Functionality Tests Group
        func_group = QGroupBox("Functionality Tests")
        func_layout = QGridLayout(func_group)

        func_tests = ["Reset Command", "SCPI Compliance"]
        for i, test in enumerate(func_tests):
            btn = TestButton(test)
            btn.clicked.connect(lambda checked, t=test: self.run_single_test(t))
            self.test_buttons[test] = btn
            func_layout.addWidget(btn, i // 2, i % 2)

        scroll_layout.addWidget(func_group)

        # Performance Tests Group
        perf_group = QGroupBox("Performance Tests")
        perf_layout = QGridLayout(perf_group)

        perf_tests = ["Response Time", "Communication Stability"]
        for i, test in enumerate(perf_tests):
            btn = TestButton(test)
            btn.clicked.connect(lambda checked, t=test: self.run_single_test(t))
            self.test_buttons[test] = btn
            perf_layout.addWidget(btn, i // 2, i % 2)

        scroll_layout.addWidget(perf_group)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        return widget

    def _create_results_tab(self) -> QWidget:
        """Create the results display tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Results summary
        summary_layout = QHBoxLayout()

        self.passed_label = QLabel("Passed: 0")
        self.passed_label.setStyleSheet("color: green; font-weight: bold; font-size: 14px;")
        summary_layout.addWidget(self.passed_label)

        self.failed_label = QLabel("Failed: 0")
        self.failed_label.setStyleSheet("color: red; font-weight: bold; font-size: 14px;")
        summary_layout.addWidget(self.failed_label)

        self.total_label = QLabel("Total: 0")
        self.total_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        summary_layout.addWidget(self.total_label)

        summary_layout.addStretch()

        self.clear_results_btn = QPushButton("Clear Results")
        self.clear_results_btn.clicked.connect(self.clear_results)
        summary_layout.addWidget(self.clear_results_btn)

        layout.addLayout(summary_layout)

        # Results display
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.results_text)

        return widget

    def _create_log_tab(self) -> QWidget:
        """Create the logging tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Log controls
        log_controls = QHBoxLayout()

        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_controls.addWidget(self.clear_log_btn)

        log_controls.addStretch()

        layout.addLayout(log_controls)

        # Log display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_text)

        return widget

    def setup_logging(self):
        """Set up logging configuration."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('instrument_test.log')
            ]
        )

    def refresh_instruments(self):
        """Refresh the list of available instruments."""
        try:
            rm = pyvisa.ResourceManager()
            resources = rm.list_resources()
            rm.close()

            self.address_combo.clear()
            self.address_combo.addItems(resources)

            if resources:
                self.log_message(f"Found {len(resources)} instruments: {', '.join(resources)}")
            else:
                self.log_message("No instruments found")

        except Exception as e:
            self.log_message(f"Error refreshing instruments: {str(e)}")
            QMessageBox.warning(self, "Warning", f"Failed to refresh instruments:\n{str(e)}")

    def run_single_test(self, test_name: str):
        """Run a single test."""
        if self.tester and self.tester.isRunning():
            QMessageBox.warning(self, "Warning", "Tests are already running!")
            return

        address = self.address_combo.currentText().strip()
        if not address:
            QMessageBox.warning(self, "Warning", "Please enter a VISA address!")
            return

        self.test_buttons[test_name].set_status("running")

        self.tester = InstrumentTester(address)
        self.tester.test_completed.connect(self.on_test_completed)
        self.tester.test_started.connect(self.on_test_started)
        self.tester.log_message.connect(self.log_message)

        self.tester.add_test(test_name)
        self.tester.start()

    def run_all_tests(self):
        """Run all available tests."""
        address = self.address_combo.currentText().strip()
        if not address:
            QMessageBox.warning(self, "Warning", "Please enter a VISA address!")
            return

        if self.tester and self.tester.isRunning():
            QMessageBox.warning(self, "Warning", "Tests are already running!")
            return

        # Reset all button states
        for btn in self.test_buttons.values():
            btn.set_status("idle")

        # Create tester and connect signals
        self.tester = InstrumentTester(address)
        self.tester.test_completed.connect(self.on_test_completed)
        self.tester.test_started.connect(self.on_test_started)
        self.tester.progress_updated.connect(self.on_progress_updated)
        self.tester.log_message.connect(self.log_message)
        self.tester.finished.connect(self.on_all_tests_finished)

        # Add all tests
        for test_name in self.test_buttons.keys():
            self.tester.add_test(test_name)

        # Update UI state
        self.run_all_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        # Start testing
        self.tester.start()
        self.log_message(f"Starting all tests on {address}")

    def stop_tests(self):
        """Stop running tests."""
        if self.tester and self.tester.isRunning():
            self.tester.terminate()
            self.tester.wait()
            self.log_message("Tests stopped by user")

        self.on_all_tests_finished()

    def on_test_started(self, test_name: str):
        """Handle test started signal."""
        if test_name in self.test_buttons:
            self.test_buttons[test_name].set_status("running")
        self.statusBar().showMessage(f"Running: {test_name}")
        self.log_message(f"Started test: {test_name}")

    def on_test_completed(self, result: TestResult):
        """Handle test completed signal."""
        # Update button status
        if result.test_name in self.test_buttons:
            status = "pass" if result.passed else "fail"
            self.test_buttons[result.test_name].set_status(status)

        # Store result
        self.test_results[result.test_name] = result

        # Update results display
        self.update_results_display()

        # Log result
        status = "PASSED" if result.passed else "FAILED"
        self.log_message(f"Test {result.test_name}: {status} - {result.message} ({result.execution_time:.3f}s)")

    def on_progress_updated(self, progress: int):
        """Handle progress update signal."""
        self.progress_bar.setValue(progress)

    def on_all_tests_finished(self):
        """Handle all tests finished."""
        self.run_all_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage("Tests completed")

        # Show summary
        passed = sum(1 for r in self.test_results.values() if r.passed)
        total = len(self.test_results)
        failed = total - passed

        self.log_message(f"All tests completed. Passed: {passed}, Failed: {failed}, Total: {total}")

    def update_results_display(self):
        """Update the results display tab."""
        # Update summary
        passed = sum(1 for r in self.test_results.values() if r.passed)
        failed = sum(1 for r in self.test_results.values() if not r.passed)
        total = len(self.test_results)

        self.passed_label.setText(f"Passed: {passed}")
        self.failed_label.setText(f"Failed: {failed}")
        self.total_label.setText(f"Total: {total}")

        # Update detailed results
        results_html = "<html><body style='font-family: monospace;'>"
        results_html += "<h3>Test Results Summary</h3>"

        for test_name, result in sorted(self.test_results.items()):
            status_color = "green" if result.passed else "red"
            status_text = "PASS" if result.passed else "FAIL"

            results_html += f"""
            <div style='margin: 10px 0; padding: 10px; border-left: 4px solid {status_color};'>
                <strong style='color: {status_color};'>{test_name}: {status_text}</strong><br>
                <small>Time: {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</small><br>
                <small>Duration: {result.execution_time:.3f}s</small><br>
                Message: {result.message}
            </div>
            """

        results_html += "</body></html>"
        self.results_text.setHtml(results_html)

    def clear_results(self):
        """Clear all test results."""
        self.test_results.clear()
        self.results_text.clear()

        # Reset button states
        for btn in self.test_buttons.values():
            btn.set_status("idle")

        self.update_results_display()
        self.log_message("Results cleared")

    def log_message(self, message: str):
        """Add a message to the log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"

        self.log_text.append(log_entry)
        logging.info(message)

        # Auto-scroll to bottom
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.End)
        self.log_text.setTextCursor(cursor)

    def clear_log(self):
        """Clear the log display."""
        self.log_text.clear()

    def closeEvent(self, event):
        """Handle application close event."""
        if self.tester and self.tester.isRunning():
            reply = QMessageBox.question(self, "Confirm Exit",
                                       "Tests are running. Stop and exit?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.tester.terminate()
                self.tester.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

# %% Main
def main():
    """Main application entry point."""
    app = QApplication(sys.argv)

    # Set application properties
    app.setApplicationName("Instrument Test Suite")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("Test Automation Solutions")

    # Create and show main window
    window = InstrumentTestGUI()
    window.show()

    # Start event loop
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
