import ctypes, sys, time, pickle, os, datetime, queue, multiprocessing, logging, signal
from picosdk.ps5000a import ps5000a as ps
from picosdk.functions import adc2mV, assert_pico_ok
import numpy as np

# Set up logging to display information, warnings, and errors
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Global variables
status = {}  # Dictionary to store the status of various operations
chandle = ctypes.c_int16()  # Handle for the PicoScope device
BUFFER_SIZE = 100000000  # Size of the buffer for storing samples
select_channels = []  # List to store selected channels
channel_range = ps.PS5000A_RANGE['PS5000A_2V']  # Default voltage range
channel_range_list = ['10mV', '20mV', '50mV', '100mV', '200mV', '500mV', '1V', '2V', '5V', '10V', '20V']  # Available voltage ranges

def get_user_settings():
    """
    Interactively prompts the user to configure the data acquisition settings.

    This function guides the user through the following steps:

    1. Channel Selection:
        - Asks the user to choose which channels (A, B, C, D) to record from.
        - Allows multiple channels to be selected.

    2. Voltage Range:
        - For each selected channel, prompts the user to set a voltage range.
        - Provides a list of valid ranges to choose from.
        - Ensures the user enters a valid range before proceeding.

    3. Sampling Rate:
        - Asks the user to specify the sampling rate in nanoseconds (ns).
        - This determines how often data points are collected for each channel.

    4. Resolution:
        - Asks the user to select the resolution of the recorded data (8 or 12 bits).
        - Higher resolution means more precise measurements.

    5. Duration:
        - Asks the user how long to record data.
        - Two options are available:
        - "time": Record for a specified number of seconds.
        - "manual": Record until the user manually stops the process.

    Returns:
        A dictionary containing the user's chosen settings:
            - channels (list): List of selected channels (e.g., ['A', 'C']).
            - voltage_ranges (dict): Channel-specific voltage ranges (e.g., {'A': '1V', 'C': '5V'}).
            - sampling_rate (int): Sampling rate in nanoseconds.
            - resolution (int): Data resolution (8 or 12).
            - duration (int or None): Recording duration in seconds (or None for manual termination).
    """
    settings = {}

    # 1. Channel Selection: Get a list of channels the user wants to record from
    settings['channels'] = select_channels() 

    # 2. Voltage Range: Get desired voltage range for each selected channel
    settings['voltage_ranges'] = {}  # Create a dictionary to store voltage ranges per channel
    for channel in settings['channels']:
        print(f"\nVoltage range options: {', '.join(channel_range_list)}") # Display available voltage ranges
        range_input = input(f"Enter voltage range for channel {channel}: ") 
        while range_input not in channel_range_list:  # Keep asking until a valid range is entered
            range_input = input(f"Invalid input. Please enter a valid voltage range for channel {channel}: ")
        settings['voltage_ranges'][channel] = range_input # Store the valid range for the current channel

    # 3. Sampling Rate: Get how often to take measurements (in nanoseconds)
    settings['sampling_rate'] = int(input("Enter sampling rate (in ns): "))

    # 4. Resolution: Get the desired precision of the measurements (8 or 12 bits)
    resolution_input = input("Enter resolution (8 or 12 bit): ")
    while resolution_input not in ['8', '12']: # Keep asking until a valid resolution is entered
        resolution_input = input("Invalid input. Please enter 8 or 12 for resolution: ")
    settings['resolution'] = int(resolution_input)

    # 5. Duration: Get how long to record for (specific time or until manually stopped)
    duration_type = input("Enter 'time' for specific duration or 'manual' for manual termination: ")
    if duration_type.lower() == 'time':
        settings['duration'] = int(input("Enter duration in seconds: "))
    else:
        settings['duration'] = None  # None indicates manual termination
        logging.info("Press Ctrl+C to terminate data collection.")

    return settings  # Return the dictionary of settings collected from the user


def open_device(resolution):
    """
    Opens and initializes a connection to the PicoScope 5000A device.

    This function performs the following steps:

    1. Resolution Mapping:
        - Takes the user-specified resolution (8 or 12 bits) as input.
        - Translates this user-friendly input into the corresponding resolution code required by the PicoScope library.
        - The `resolution_map` dictionary stores this mapping.

    2. Device Opening:
        - Calls the `ps.ps5000aOpenUnit` function from the PicoScope library to attempt to open the device.
        - Passes:
            - `chandle`: A reference to a variable where the device handle will be stored if successful.
            - `None`:  No specific serial number (opens the first available device).
            - `resolution_setting`: The correctly mapped resolution code.
        - Stores the result of the opening operation in the `status["openunit"]` variable.

    3. Error Handling:
        - Checks if the device was opened successfully using `assert_pico_ok`. If not:
            - It examines the specific error code stored in `power_status`.
            - If the error is related to the power source (codes 286 or 282), it attempts to change the power source using `ps.ps5000aChangePowerSource`.
            - If the power source change is successful, it re-attempts to open the device.
            - If any other error occurs, or if the power source change fails, an exception is raised to signal that the device could not be opened.

    4. Logging:
        - If the device is successfully opened, a log message is created to indicate this.
    
    Globals:
        - chandle: A global variable to hold the device handle for future interactions with the PicoScope.

    Raises:
        - Exception: If the device cannot be opened for any reason other than a correctable power source issue.

    Example Usage:
        open_device(12)  # Opens the device with 12-bit resolution
    """

    global chandle  # Make the chandle variable global to be accessible throughout the script

    # Define a dictionary to map user-friendly resolution to PicoScope specific constants
    resolution_map = {
        8: ps.PS5000A_DEVICE_RESOLUTION["PS5000A_DR_8BIT"],
        12: ps.PS5000A_DEVICE_RESOLUTION["PS5000A_DR_12BIT"]
    }
    resolution_setting = resolution_map[resolution]  # Get the correct resolution constant

    # Attempt to open the device with the given resolution
    status["openunit"] = ps.ps5000aOpenUnit(ctypes.byref(chandle), None, resolution_setting)

    try:
        # Check for any errors during device opening
        assert_pico_ok(status["openunit"])
    except:  # If an error occurs
        power_status = status["openunit"]  
        if power_status in [286, 282]:  # If the error is power-related (specific codes)
            # Attempt to change power source and retry opening the device
            status["changePowerSource"] = ps.ps5000aChangePowerSource(chandle, power_status)
            assert_pico_ok(status["changePowerSource"]) 
        else:
            raise  # Raise the original exception for other errors

    logging.info("Device opened successfully")  # Log a success message


def select_channels():
    """
    Interactively prompts the user to select which channels of the PicoScope to activate.

    This function does the following:

    1. Defines Available Channels:
        - Creates a list `available_channels` that contains all the possible channels the PicoScope supports ('A', 'B', 'C', and 'D').

    2. User Input:
        - Prints a message to the user, asking them to enter the channels they want to use.
        - The user can enter multiple channels separated by commas (e.g., "A, C, D").
        - Calls the `input()` function to get the user's response.

    3. Input Processing:
        - Converts the user's input to uppercase using `.upper()` so that channel letters are consistent.
        - Splits the input into a list of individual channels using `.split(',')`.
        - Cleans up any extra spaces around the channel names using a list comprehension with `.strip()`.
        - Filters out any invalid channels that the user might have entered by comparing to the `available_channels` list.

    4. Global Update (Optional):
        - The use of `global selected_channels` is optional and depends on how you manage variables in your larger program. 
        - If `selected_channels` is needed outside this function, you should make it global so the changes made here are accessible elsewhere.

    5. Return Selected Channels:
        - Returns the final list of valid channels selected by the user.

    Example Usage:
        channels_to_record = select_channels()
        #  If the user entered "A, c ", `channels_to_record` would be ['A', 'C']
    """
    global selected_channels # Optional: If you need to access selected_channels outside the function
    
    # List of all available channels on the PicoScope device
    available_channels = ['A', 'B', 'C', 'D']

    # Ask the user to input the channels they want to use, separated by commas
    selected_channels = input("Enter the channels you want to use (A, B, C, D), separated by commas: ").upper().split(',')

    # Clean up and validate the user's input
    selected_channels = [ch.strip() for ch in selected_channels if ch.strip() in available_channels]

    return selected_channels # Return the list of valid selected channels

def setup_channels(selected_channels, voltage_ranges):
    """
    Configures the selected PicoScope channels for data acquisition.

    This function performs the following tasks:

    1. Channel and Range Mapping:
        - Initializes two dictionaries:
            - `channel_mapping`: Maps user-friendly channel names ('A', 'B', 'C', 'D') to their corresponding PicoScope library constants.
            - `range_mapping`: Maps user-friendly voltage range strings (e.g., '1V') to their corresponding PicoScope library constants.

    2. Channel Configuration:
        - Iterates over ALL possible channels ('A', 'B', 'C', 'D'):
            - Determines if the current channel is in the `selected_channels` list.
            - If selected:
                - Sets `enabled` to 1 (True).
                - Looks up the user-specified voltage range for the channel in the `voltage_ranges` dictionary and translates it to the corresponding PicoScope constant.
            - If not selected:
                - Sets `enabled` to 0 (False) to disable the channel.
                - Uses a default voltage range of 2V. 
        - Calls the `ps.ps5000aSetChannel` function from the PicoScope library to configure each channel:
            - `chandle`: Device handle obtained from the `open_device` function.
            - `channel_mapping[channel]`: The correct channel identifier for the PicoScope library.
            - `enabled`: Whether the channel is enabled (1) or disabled (0).
            - `ps.PS5000A_COUPLING['PS5000A_DC']`: Sets the coupling type to DC (direct current).
            - `channel_range`: The appropriate voltage range for the channel.
            - `0.0`: Analogue offset (set to 0).
        - Stores the status of the channel setup operation in the `status` dictionary (e.g., `status["setChA"]`).
        - Checks for errors using `assert_pico_ok`. If an error occurs, it raises an exception.

    3. Logging:
        - If all channels are set up successfully, a log message is created indicating which channels were configured.

    Args:
        selected_channels (list): A list of strings representing the channels the user wants to record from (e.g., ['A', 'C']).
        voltage_ranges (dict): A dictionary mapping channel names to their corresponding voltage range strings (e.g., {'A': '1V', 'C': '5V'}).

    Raises:
        Exception: If there is an error setting up any of the selected channels.
    """

    # Create dictionaries to map channel names and voltage ranges to PicoScope constants
    channel_mapping = {
        'A': ps.PS5000A_CHANNEL['PS5000A_CHANNEL_A'],
        'B': ps.PS5000A_CHANNEL['PS5000A_CHANNEL_B'],
        'C': ps.PS5000A_CHANNEL['PS5000A_CHANNEL_C'],
        'D': ps.PS5000A_CHANNEL['PS5000A_CHANNEL_D']
    }

    range_mapping = {
        '10mV': ps.PS5000A_RANGE['PS5000A_10MV'],
        '20mV': ps.PS5000A_RANGE['PS5000A_20MV'],
        '50mV': ps.PS5000A_RANGE['PS5000A_50MV'],
        '100mV': ps.PS5000A_RANGE['PS5000A_100MV'],
        '200mV': ps.PS5000A_RANGE['PS5000A_200MV'],
        '500mV': ps.PS5000A_RANGE['PS5000A_500MV'],
        '1V': ps.PS5000A_RANGE['PS5000A_1V'],
        '2V': ps.PS5000A_RANGE['PS5000A_2V'],
        '5V': ps.PS5000A_RANGE['PS5000A_5V'],
        '10V': ps.PS5000A_RANGE['PS5000A_10V'],
        '20V': ps.PS5000A_RANGE['PS5000A_20V'],
        }

    # Configure each channel
    for channel in 'ABCD':  # Iterate through all possible channels
        enabled = 1 if channel in selected_channels else 0  # Enable if selected, disable if not
        channel_range = range_mapping[voltage_ranges[channel]] if channel in selected_channels else ps.PS5000A_RANGE['PS5000A_2V'] # Set range if selected, use default 2V if not
        status[f"setCh{channel}"] = ps.ps5000aSetChannel(chandle,
                                                        channel_mapping[channel],
                                                        enabled,
                                                        ps.PS5000A_COUPLING['PS5000A_DC'],
                                                        channel_range,
                                                        0.0)  # analogue_offset
        assert_pico_ok(status[f"setCh{channel}"]) #Check if setting up the channel was successful

    logging.info(f"Channels {', '.join(selected_channels)} set up successfully")  # Log success message


def set_buffers(selected_channels):
    """
    Sets up data buffers in the PicoScope's memory for each selected channel.

    This function is a crucial step in data acquisition. It prepares the PicoScope to store
    the incoming data from the selected channels. Here's how it works:

    1. Global Buffer Initialization:
        - Declares `bufferMax` as a global variable. This dictionary will store the maximum buffer size for each selected channel.
        - Initializes `bufferMax` as a dictionary where the keys are the selected channel names ('A', 'B', 'C', 'D')
            and the values are NumPy arrays filled with zeros. These arrays will act as the buffers to hold the data.

    2. Channel Mapping:
        - Creates a dictionary `channel_mapping` that maps human-readable channel names (e.g., 'A') to the 
            corresponding PicoScope channel constants (e.g., `ps.PS5000A_CHANNEL['PS5000A_CHANNEL_A']`). 
            This makes the code easier to read and understand.

    3. Buffer Configuration:
        - Iterates through each of the `selected_channels`.
        - For each channel:
            - Calls the `ps.ps5000aSetDataBuffers` function from the PicoScope library to allocate memory for the data buffer.
                - `chandle`: The device handle (from `open_device`) to communicate with the PicoScope.
                - `channel_mapping[channel]`: The correct channel identifier for the PicoScope.
                - `bufferMax[channel].ctypes.data_as(ctypes.POINTER(ctypes.c_int16))`: A pointer to the start of the NumPy buffer array.
                - `None`: No downsampling is being applied in this case.
                - `BUFFER_SIZE`: The maximum size of the buffer (how many data points it can store).
                - `0`: A parameter related to segmenting data (not used here, so set to 0).
                - `ps.PS5000A_RATIO_MODE['PS5000A_RATIO_MODE_NONE']`: Indicates no special ratio mode for the data.
            - Stores the status of the buffer setup operation in the `status` dictionary (e.g., `status["setDataBuffersA"]`).
            - Checks for errors using `assert_pico_ok`. If an error occurs, it raises an exception.

    4. Logging:
        - If all buffers are set up successfully, a log message is created to indicate this.

    Args:
        selected_channels (list): A list of strings representing the channels the user wants to record from (e.g., ['A', 'C']).

    Raises:
        Exception: If there is an error setting up the data buffers for any of the selected channels.
    """
    
    global bufferMax  # Make bufferMax global so it can be used elsewhere in the code

    # Initialize a dictionary to store the data buffers for each selected channel
    bufferMax = {ch: np.zeros(BUFFER_SIZE, dtype=np.int16) for ch in selected_channels}

    # Mapping of channel names to PicoScope channel constants
    channel_mapping = {
        'A': ps.PS5000A_CHANNEL['PS5000A_CHANNEL_A'],
        'B': ps.PS5000A_CHANNEL['PS5000A_CHANNEL_B'],
        'C': ps.PS5000A_CHANNEL['PS5000A_CHANNEL_C'],
        'D': ps.PS5000A_CHANNEL['PS5000A_CHANNEL_D']
    }

    # Set up data buffers for each selected channel
    for channel in selected_channels:
        status[f"setDataBuffers{channel}"] = ps.ps5000aSetDataBuffers(
            chandle,                                   # Device handle
            channel_mapping[channel],                  # Channel identifier
            bufferMax[channel].ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),  # Pointer to the buffer
            None,                                      # No downsampling
            BUFFER_SIZE,                               # Buffer size
            0,                                         # Segment index (not used here)
            ps.PS5000A_RATIO_MODE['PS5000A_RATIO_MODE_NONE'] # Ratio mode (none)
        )
        assert_pico_ok(status[f"setDataBuffers{channel}"])  # Check for errors

    logging.info("Buffers set successfully")  # Log success message


def run_streaming(sampling_rate):
    """
    Starts the PicoScope in continuous data streaming mode.

    This function configures the PicoScope to continuously collect data from the 
    selected channels at the specified sampling rate. Here's what it does:

    1. Sample Interval and Units:
        - Creates a `ctypes.c_int32` object named `sampleInterval` to store the sampling rate value.
        - Specifies the sampling rate units as nanoseconds (ns) using `ps.PS5000A_TIME_UNITS['PS5000A_NS']`.

    2. Streaming Parameters:
        - Sets the following parameters for streaming:
            - `maxPreTriggerSamples`: Number of samples to capture before a trigger event (set to 0 for no pre-triggering).
            - `autoStopOn`: Whether to stop automatically after a certain number of samples (set to 0 to disable).
            - `downsampleRatio`: Factor by which to reduce the data rate (set to 1 for no downsampling).

    3. Start Streaming:
        - Calls the `ps.ps5000aRunStreaming` function from the PicoScope library to initiate streaming.
        - Passes the following arguments:
            - `chandle`: Device handle obtained from the `open_device` function.
            - `sampleInterval`: The sampling rate.
            - `sampleUnits`: The units of the sampling rate (nanoseconds).
            - `maxPreTriggerSamples`:  (0 for no pre-triggering).
            - `BUFFER_SIZE`: The maximum number of samples to collect in a single block.
            - `autoStopOn`:  (0 to disable).
            - `downsampleRatio`:  (1 for no downsampling).
            - `ps.PS5000A_RATIO_MODE['PS5000A_RATIO_MODE_NONE']`: Indicates no special ratio mode for the data.
            - `BUFFER_SIZE`: The size of the buffer to use for streaming.
        - Stores the status of the streaming operation in the `status["runStreaming"]` variable.
        - Checks for errors using `assert_pico_ok`. If an error occurs, it raises an exception.

    4. Logging:
        - If streaming starts successfully, a log message is created indicating the sample interval.

    Args:
        sampling_rate (int): The sampling rate in nanoseconds.

    Raises:
        Exception: If there is an error starting the streaming mode.
    """
    sampleInterval = ctypes.c_int32(sampling_rate) 
    sampleUnits = ps.PS5000A_TIME_UNITS['PS5000A_NS']
    maxPreTriggerSamples = 0
    autoStopOn = 0
    downsampleRatio = 1

    status["runStreaming"] = ps.ps5000aRunStreaming(chandle,
                                                    ctypes.byref(sampleInterval),
                                                    sampleUnits,
                                                    maxPreTriggerSamples,
                                                    BUFFER_SIZE,
                                                    autoStopOn,
                                                    downsampleRatio,
                                                    ps.PS5000A_RATIO_MODE['PS5000A_RATIO_MODE_NONE'],
                                                    BUFFER_SIZE)
    assert_pico_ok(status["runStreaming"]) #Check if runStreaming call was successful
    
    logging.info(f"Streaming started with sample interval: {sampleInterval.value} ns")
    
    
# Global flag to indicate if the program should exit
exit_event = multiprocessing.Event()


def signal_handler(signum, frame):
    """
    Gracefully handles interrupt signals (like Ctrl+C) to stop data collection.

    This function is called when the user presses Ctrl+C (or sends a similar interrupt signal). It sets a global flag 
    to signal that the data collection process should stop.

    Args:
        signum (int): The signal number (not used in this function, but required for signal handlers).
        frame (frame object): The current stack frame (not used in this function, but required for signal handlers).
    """
    exit_event.set()  # Set the exit_event flag to signal that the program should terminate
    logging.info("Interrupt received, preparing to exit...")


# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)

def streaming_callback(handle, noOfSamples, startIndex, overflow, triggerAt, triggered, autoStop, param):
    """
    Handles data streaming callbacks from the PicoScope.

    This function is called by the PicoScope library whenever a new batch of data is available. 
    It does the following:

    1. Check for Exit Signal:
        - If the `exit_event` flag is set (e.g., by Ctrl+C), the function returns immediately to allow the main loop to exit.

    2. Overflow Handling:
        - If an overflow occurred (meaning some data was lost), it logs a warning message indicating how many samples were lost.

    3. Data Transfer:
        - Iterates over each of the `selected_channels`.
        - Copies the new data samples from the PicoScope's `bufferMax` to the `bufferComplete` buffer for each channel.
        - This is done to build up a complete buffer of data that can be processed later.

    4. Update Sample Count:
        - Increments the `nextSample` counter by the number of new samples received.
        - This keeps track of how much data has been collected in total.

    Args:
        handle: The device handle (not used in this function).
        noOfSamples (int): The number of new samples received.
        startIndex (int): The starting index in the buffer where the new samples are located.
        overflow (int): Indicates whether an overflow occurred (1 if overflow, 0 otherwise).
        triggerAt (int): Not used in this function.
        triggered (int): Not used in this function.
        autoStop (int): Not used in this function.
        param: Not used in this function.
    """
    global bufferComplete, nextSample, selected_channels
    if exit_event.is_set():
        return
    if overflow:
        logging.warning(f"Overflow occurred. Lost {noOfSamples} samples.")
    for channel in selected_channels:
        bufferComplete[channel][nextSample:nextSample + noOfSamples] = bufferMax[channel][startIndex:startIndex + noOfSamples]
    nextSample += noOfSamples


# Define a function pointer to the streaming callback function for the PicoScope library
cFuncPtr = ps.StreamingReadyType(streaming_callback)


def get_data():
    """
    Retrieves the latest data from the PicoScope streaming buffer.

    This function calls the `ps5000aGetStreamingLatestValues` function from the PicoScope library to fetch
    the most recent data that has been streamed into the buffer. It also returns the current value of 
    the `nextSample` variable, which indicates how many samples have been collected so far.

    Returns:
        int: The number of samples currently in the `bufferComplete` buffer.
    """
    # Get the latest values from the streaming buffer
    status["getStreamingLatestValues"] = ps.ps5000aGetStreamingLatestValues(chandle, cFuncPtr, None)
    return nextSample

def save_data_worker(data_queue, output_folder, exit_event):
    """
    This function runs as a separate process to save data received from the main data collection process.

    It continuously monitors a queue for incoming data, processes each batch, 
    and saves the data to files. It also includes a mechanism to periodically check 
    the queue size and warn if it's filling up, which could indicate a problem.

    Args:
        data_queue (multiprocessing.Queue): The queue from which the worker retrieves data to save.
        output_folder (str): The folder where the data files will be saved.
        exit_event (multiprocessing.Event): An event object that signals when the worker should stop.

    Steps:

    1. Initialization:
        - data_counter: Initializes a counter to track the number of data batches saved.
        - last_queue_check_time: Stores the time of the last queue size check.
        - queue_check_interval: Sets the time interval (in seconds) between queue size checks (default is 5 seconds).

    2. Main Loop:
        - The loop continues running until the `exit_event` is set (usually triggered by Ctrl+C or another signal).
        - It tries to get a batch of channel data from the `data_queue`.

    3. Data Retrieval:
        - data_queue.get(timeout=0.1): Attempts to retrieve data from the queue with a 0.1 second timeout. 
            - If no data is available within the timeout, it continues to the next iteration.
            - If `None` is received, it means the main process has sent a signal to terminate, so the loop breaks.

    4. Data Saving (if data is available):
        - Logs a message indicating that a data batch is being processed.
        - Iterates over each channel in the `channel_data` dictionary:
            - Creates a folder for the channel if it doesn't exist.
            - Constructs the file path where the data will be saved.
            - Uses `np.save` to save the data array to a `.npy` file (NumPy's binary format).
            - Logs a message indicating that the data was saved, along with the channel name and the number of samples.

    5. Data Counter Update:
        - Increments the `data_counter` after saving a batch.

    6. Queue Size Check:
        - Periodically checks the size of the data_queue to see if it's getting too large.
        - If the time since the last check exceeds the `queue_check_interval`, it calls the `check_queue_size` function (defined elsewhere) to log a warning if necessary.
        - Updates the `last_queue_check_time` to the current time.

    7. Exception Handling:
        - queue.Empty: If the queue is empty (within the timeout), the loop continues to the next iteration.
        - Exception: Any other errors are logged, but only if the `exit_event` is not set (to avoid logging errors during shutdown).

    8. Termination:
        - After the loop ends (due to the exit event or an error), a final log message indicates that the worker has finished.
    """
    data_counter = 0
    last_queue_check_time = time.time()
    queue_check_interval = 5  # Check queue size every 5 seconds

    while not exit_event.is_set():
        try:
            channel_data = data_queue.get(timeout=0.1)
            if channel_data is None:  # Check for termination signal
                break

            logging.info(f"Processing data batch {data_counter}")

            for channel, data in channel_data.items():
                channel_folder = os.path.join(output_folder, f"channel_{channel.lower()}")
                os.makedirs(channel_folder, exist_ok=True)

                file_path = os.path.join(channel_folder, f'data_{data_counter}.npy')
                np.save(file_path, data)

                logging.info(f"Data {data_counter} saved for channel {channel}, Sample #: {len(data)}")

            data_counter += 1

            # Check queue size periodically
            current_time = time.time()
            if current_time - last_queue_check_time >= queue_check_interval:
                check_queue_size(data_queue)
                last_queue_check_time = current_time

        except queue.Empty:
            continue
        except Exception as e:
            if not exit_event.is_set():
                logging.error(f"Error in save_data_worker: {e}")
    logging.info("Save data worker finished")


def main_loop(selected_channels, data_queue, duration, exit_event):
    """
    This function is the core of the data collection process. 

    It continuously acquires data from the selected PicoScope channels, 
    buffers the data, and sends batches of data to a separate worker process for saving. 
    The loop runs until either a specified duration is reached or the user manually 
    terminates it with an interrupt signal (e.g., Ctrl+C).

    Args:
        selected_channels (list): A list of strings representing the active channels (e.g., ['A', 'C']).
        data_queue (multiprocessing.Queue): A queue used to transfer data to the save_data_worker process.
        duration (int or None): The duration of data collection in seconds (or None for manual termination).
        exit_event (multiprocessing.Event): An event object used to signal the loop to stop.

    Steps:

    1. Global Variable Initialization:
        - Declares `nextSample` and `bufferComplete` as global variables.
        - Initializes `bufferComplete` as a dictionary where the keys are the selected channel names 
            and the values are NumPy arrays of zeros. These arrays will act as buffers to temporarily store incoming data.
        - Sets `nextSample` to 0, which tracks the next available index in the buffers.

    2. Transfer Size:
        - Calculates the `transfer_size` as 10% of the `BUFFER_SIZE`. 
            This determines how much data is accumulated in the buffers before being sent to the worker process for saving.

    3. Start Time:
        - Records the `start_time` to track the elapsed time during data collection.

    4. Main Loop:
        - The loop continues running until the `exit_event` is set (e.g., by Ctrl+C or another signal).
        - Calls the `get_data` function to retrieve the latest data from the PicoScope streaming buffer.
        - If the `nextSample` counter reaches or exceeds the `transfer_size`, it means the buffers are ready to be transferred:
            - Creates a new dictionary `data_to_save` containing copies of the filled portions of the buffers.
            - Puts this `data_to_save` dictionary into the `data_queue`, signaling the worker process to save it.
            - Logs a message indicating that data has been put into the queue.
            - Resets the `bufferComplete` buffers and the `nextSample` counter for the next batch of data.
        - Checks if a duration was specified and if that duration has been reached:
            - If so, logs a message indicating that data collection has stopped due to reaching the specified duration.
            - Breaks out of the loop to end data collection.
        - Introduces a small delay using `time.sleep(0.001)` to avoid excessive CPU usage.

    5. Exception Handling:
        - try...except block is used to catch any errors that might occur during the loop.
        - If an exception occurs and the `exit_event` is not set (i.e., the error is not due to a termination signal), 
            it logs an error message with details of the exception.
        - finally block is executed regardless of whether an exception occurred. It logs a message indicating that data collection has stopped.
    """
    global nextSample, bufferComplete

    # Initialize buffers for each channel and the next sample index
    bufferComplete = {ch: np.zeros(BUFFER_SIZE, dtype=np.int16) for ch in selected_channels}
    nextSample = 0

    # Calculate transfer size as 10% of buffer size
    transfer_size = BUFFER_SIZE // 10

    # Get start time for duration tracking
    start_time = time.time()

    try:
        while not exit_event.is_set():
            new_samples = get_data() # Get the latest data from the PicoScope
            
            # Check if the buffer is ready to be transferred
            if nextSample >= transfer_size:
                # Prepare data for saving
                data_to_save = {ch: bufferComplete[ch][:nextSample].copy() for ch in selected_channels}
                # Put the data in the queue for the saving process
                data_queue.put(data_to_save)
                logging.info(f"Put in Queue {nextSample}")

                # Reset buffer and nextSample for the next batch
                bufferComplete = {ch: np.zeros(BUFFER_SIZE, dtype=np.int16) for ch in selected_channels}
                nextSample = 0

            # Check if the specified duration has elapsed
            if duration is not None and time.time() - start_time >= duration:
                logging.info(f"Specified duration of {duration} seconds reached. Stopping data collection.")
                break
            
            time.sleep(0.001) # Small delay to prevent excessive CPU usage

    except Exception as e:
        if not exit_event.is_set():
            logging.error(f"Error in main_loop: {e}")
    finally:
        logging.info("Data collection stopped.")

def check_queue_size(queue, warning_threshold=0.5, critical_threshold=0.8):
    """
    Monitors the size of a data queue and logs warnings or critical alerts if it becomes too full.

    This function is designed to help you keep an eye on how much data is accumulating in the queue. 
    It calculates the current fill level of the queue and compares it to predefined thresholds to determine 
    if a warning or critical alert is needed.

    Args:
        queue (multiprocessing.Queue): The queue object to check.
        warning_threshold (float, optional): The fill ratio at which a warning should be logged (default: 0.5, meaning 50% full).
        critical_threshold (float, optional): The fill ratio at which a critical alert should be logged (default: 0.8, meaning 80% full).

    Returns:
        float: The current fill ratio of the queue (a value between 0 and 1).

    Steps:

    1. Queue Size Calculation:
        - Gets the current number of items in the queue using `queue.qsize()` and stores it in `current_size`.
        - Gets the maximum capacity of the queue using `queue._maxsize` and stores it in `max_size`.
        - Calculates the `fill_ratio` as `current_size` divided by `max_size`.
            - If the `max_size` is 0 (meaning the queue is unbounded), the `fill_ratio` is set to 0.

    2. Threshold Comparison:
        - Checks if the `fill_ratio` is greater than or equal to the `critical_threshold`:
            - If true, logs a CRITICAL level message indicating that the queue is critically full, 
            along with the current and maximum size and the fill ratio as a percentage.
        - If the `fill_ratio` is not above the critical threshold, checks if it's greater than or equal to the `warning_threshold`:
            - If true, logs a WARNING level message indicating that the queue is filling up, 
            along with the current and maximum size and the fill ratio as a percentage.
        - If neither threshold is met, no message is logged.

    3. Return Fill Ratio:
        - Returns the calculated `fill_ratio` so it can be used by other parts of the code if needed.

    Example Usage:
        fill_level = check_queue_size(data_queue)
        if fill_level > 0.9:  # Custom check
            # Take some action to prevent the queue from getting completely full
    """
    current_size = queue.qsize()  # Get the current number of items in the queue
    max_size = queue._maxsize  # Get the maximum capacity of the queue
    fill_ratio = current_size / max_size if max_size > 0 else 0  # Calculate the fill ratio

    # Log a critical message if the queue is very full
    if fill_ratio >= critical_threshold:
        logging.critical(f"Queue is critically full! {current_size}/{max_size} ({fill_ratio:.2%})")

    # Log a warning message if the queue is starting to fill up
    elif fill_ratio >= warning_threshold:
        logging.warning(f"Queue is filling up! {current_size}/{max_size} ({fill_ratio:.2%})")

    return fill_ratio  # Return the fill ratio in case it's needed elsewhere

        
if __name__ == "__main__":
    """
    This block of code is the main entry point of the program. 
    It sets up the environment, configures the PicoScope, initiates data collection,
    and ensures proper cleanup after data collection is complete.

    Steps:

    1. Freeze Support (Windows Only):
        - This line is necessary for running multiprocessing on Windows systems. It ensures that the child processes can start correctly.

    2. Create Output Directory:
        - Gets the current time and formats it as a string for use in the directory name.
        - Creates a directory named 'data' followed by the timestamp (e.g., data0715_152130) in the current working directory.
        - This directory will store the recorded data files.
        - `os.makedirs` creates the directory, and `exist_ok=True` ensures that no errors are raised if the directory already exists.
        - Logs a message confirming the directory creation.

    3. Get User Settings:
        - Calls the `get_user_settings` function to get configuration settings from the user interactively.
        - Stores the returned settings dictionary in the `settings` variable.
        - Extracts the `selected_channels` from the settings.

    4. Initialize and Configure PicoScope:
        - Calls `open_device` to establish a connection to the PicoScope using the resolution specified in the settings.
        - Calls `setup_channels` to configure the selected channels with their respective voltage ranges.
        - Calls `set_buffers` to allocate memory buffers for the selected channels.
        - Calls `run_streaming` to start the PicoScope in streaming mode at the specified sampling rate.
        - Records the `start_time` for later calculations.

    5. Set Up Data Queue and Saving Process:
        - Creates a multiprocessing `Queue` named `data_queue` with a maximum size of 20. This queue will hold data batches before they are saved to disk.
        - Creates a multiprocessing `Process` named `save_process`.
            - `target=save_data_worker`: Specifies the function that will run in this process.
            - `args=(data_queue, output_folder, exit_event)`: Passes the necessary arguments to the `save_data_worker` function.
        - Starts the `save_process` to run in parallel with the main data collection loop.

    6. Main Data Collection Loop:
        - Encloses the main data collection loop in a `try...except...finally` block to handle potential errors gracefully.
        - Calls `main_loop` to start data acquisition from the selected channels.
        - This function will run until the specified duration is reached or the `exit_event` is set.

    7. Error Handling:
        - If any exceptions occur during data collection (except those related to the termination signal), an error message is logged.

    8. Clean Up and Close:
        - `finally` block is always executed, whether an error occurred or not.
        - Sets the `exit_event` to signal the termination of both the main loop and the `save_process`.
        - Calculates the `process_time` by subtracting the `start_time` from the current time.
        - Logs a message indicating the total processing time.
        - Puts `None` in the `data_queue` to signal the save process to terminate.
        - Waits for the `save_process` to finish with a timeout of 5 seconds.
        - If the `save_process` is still alive after the timeout, it's forcibly terminated and then joined to ensure it completes.
        - Logs messages to confirm file saving, device closing, and program termination.
    """
    print("*****PicoScope 5000A Data Acquisition and Analysis Tool by M.J*****\n\n")
    
    multiprocessing.freeze_support()  # Necessary for Windows

    # Create a directory for storing data with a timestamp
    current_time = datetime.datetime.now().strftime("%m%d_%H%M%S")
    output_folder = f"data{current_time}"
    os.makedirs(output_folder, exist_ok=True)
    logging.info(f"Directory created: {output_folder}")

    # Get user settings
    settings = get_user_settings()
    selected_channels = settings['channels']
    
    # Initialize and set up the PicoScope
    open_device(settings['resolution'])
    setup_channels(selected_channels, settings['voltage_ranges'])
    set_buffers(selected_channels)
    run_streaming(settings['sampling_rate'])
    
    start_time = time.time()

    # Set up the data queue and start the save process
    data_queue = multiprocessing.Queue(maxsize=20)
    save_process = multiprocessing.Process(target=save_data_worker, args=(data_queue, output_folder, exit_event))
    save_process.start()
    
    try:
        # Start the main data collection loop
        main_loop(selected_channels, data_queue, settings['duration'], exit_event)
    except Exception as e:
        if not exit_event.is_set():
            logging.error(f"Error in main process: {e}")
    finally:
        # Clean up and close the program
        exit_event.set()
        end_time = time.time()
        process_time = end_time - start_time
        logging.info(f"Process time: {process_time} seconds")

        # Ensure the save process receives the termination signal
        data_queue.put(None)
        
        # Wait for the save process to finish with a timeout
        save_process.join(timeout=5)
        
        # If the process is still alive after timeout, terminate it
        if save_process.is_alive():
            logging.warning("Save process did not terminate gracefully. Forcing termination.")
            save_process.terminate()
            save_process.join()

        logging.info(f"Files saved to {output_folder}")
        ps.ps5000aStop(chandle)
        ps.ps5000aCloseUnit(chandle)
        logging.info("Device closed")
        logging.info("Data saved and program terminated")
