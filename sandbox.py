# -*- coding: utf-8 -*-
"""
Created on Mon Aug 18 11:29:47 2025

@author: wwallace
"""

import pyvisa

rm = pyvisa.ResourceManager()
# inst = rm.open_resource("ASRL5::INSTR")
inst = rm.open_resource('GPIB0::19::INSTR')
inst.clear()
inst.write_termination = "\n"
inst.read_termination = "\n"
inst.timeout = 5e3
inst.write_termination = "\n"
# inst.flush(pyvisa.constants.BufferType.input)
inst.flush(pyvisa.constants.BufferType.io_in)
inst.flush(pyvisa.constants.BufferType.io_out)
inst.flush(pyvisa.constants.BufferOperation.flush_transmit_buffer)
inst.flush(pyvisa.constants.BufferOperation.flush_write_buffer)
# inst.flush(pyvisa.constants.BufferType.ouput)

inst.close()
rm.close()
