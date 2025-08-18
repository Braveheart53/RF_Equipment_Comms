# Items to try on the E8257D SigGen

# clear buffers, try this first
    import pyvisa
    rm = pyvisa.ResourceManager()
    instrument = rm.open_resource('ASRL::5') # Replace with your instrument's address
    instrument.clear() # Clears the instrument's buffers

# increase time out
    instrument.timeout = 5000 # Set timeout to 5000 ms (5 seconds)

# close the connection
    instrument.close()
    rm.close()

# maybe see errors in the above
    try:
        # Perform instrument operations
    except pyvisa.errors.VisaIOError as e:
        print(f"VISA I/O Error: {e}")
        # Implement retry logic or instrument reset

# Termination of commands
    instrument.write_termination = '\n'
    instrument.read_termination = '\n'
