import numpy as np
import matplotlib.pyplot as plt

def load_npy(file_path, samples=None):
    adc_data = np.load(file_path)
    if samples:
        if samples > 0:
            adc_data = adc_data[-samples:]
        else:
            adc_data = adc_data[:samples]
    return adc_data.astype(np.float64)

def process_and_plot_data(adc_data, voltage_range, sampling_interval_ns, file_paths):
    print(f"ADC data - min: {np.min(adc_data)}, max: {np.max(adc_data)}")
    
    adc_min, adc_max = np.min(adc_data), np.max(adc_data)
    mv_data = (adc_data - adc_min) * (voltage_range * 1000) / (adc_max - adc_min)

    time = np.arange(0, len(mv_data)) * (sampling_interval_ns / 1e9)

    plt.figure(figsize=(12, 6))
    plt.plot(time, mv_data)
    plt.title('PicoScope Data Visualization')
    plt.xlabel('Time (s)')
    plt.ylabel('Voltage (mV)')
    plt.grid(True)

    if len(file_paths) > 1:
        transition_point = len(mv_data) // 2
        plt.axvline(x=time[transition_point], color='r', linestyle='--', label='File Transition')
        plt.legend(loc='upper right')

    plt.show()

    print(f"Data shape: {mv_data.shape}")
    print(f"Time range: {time[-1]:.9f} seconds")
    print(f"Voltage data min: {np.min(mv_data):.2f} mV, max: {np.max(mv_data):.2f} mV")

# 사용자 입력
file_paths = input("Enter the path(s) to your .npy file(s), separated by comma if two files: ").split(',')
file_paths = [path.strip() for path in file_paths]
voltage_range = float(input("Enter the voltage range (in Volts): "))
sampling_interval_ns = float(input("Enter the sampling interval (in ns): "))

if len(file_paths) == 1:
    adc_data = load_npy(file_paths[0])
elif len(file_paths) == 2:
    adc_data1 = load_npy(file_paths[0], samples=-10000)
    adc_data2 = load_npy(file_paths[1], samples=10000)
    adc_data = np.concatenate((adc_data1, adc_data2))
else:
    print("Please enter either one or two file paths.")
    exit()

process_and_plot_data(adc_data, voltage_range, sampling_interval_ns, file_paths)