import os
import platform
import re
import subprocess
import time

import psutil


class sensor:
    # Main class for fetching and tracking our stats
    def __init__(self):
        self.stats = {
            "CPU Usage": [],
            "CPU Frequency": [],
            "CPU Temperature": [],
            "RAM Usage": [],
            "RAM Frequency": [],
            "GPU Temperature": [],
            "GPU Throttle Temperature": [],
            "GPU Core Frequency": [],
            "GPU Memory Frequency": [],
            "GPU Memory": [],
            "GPU Memory Usage": [],
            "GPU Fan Speed": [],
            "GPU Fan Speed RPM": [],
            "GPU Power": [],
        }

        self.units = {
            "CPU Usage": "%",
            "CPU Frequency": "MHz",
            "CPU Temperature": "°C",
            "RAM Usage": "%",
            "RAM Frequency": "MHz",
            "GPU Temperature": "°C",
            "GPU Throttle Temperature": "°C",
            "GPU Core Frequency": "MHz",
            "GPU Memory Frequency": "MHz",
            "GPU Memory": "MiB",
            "GPU Memory Usage": "MiB",
            "GPU Fan Speed": "%",
            "GPU Fan Speed RPM": "RPM",
            "GPU Power": "W",
        }

        self.component_names = {
            "CPU": self.get_cpu_name(),
            "GPU": self.get_gpu_name(),
        }
        self._ram_frequency_cache = None
        self._ram_frequency_last_update = 0
        self._ram_frequency_refresh_s = 300

    def update_stats(self, key, value):
        if value == "Unknown" or value is None:
            return "Unknown"

        try:
            # Convert value to float (if numeric) and update the history.
            value = float(value)
            if key not in self.stats:
                self.stats[key] = []
            self.stats[key].append(value)

            # If more than 50 entries, preserve the current min and max.
            if len(self.stats[key]) > 50:
                current_min = min(self.stats[key])
                current_max = max(self.stats[key])
                removed = False
                for i in range(len(self.stats[key])):
                    if self.stats[key][i] != current_min and self.stats[key][i] != current_max:
                        self.stats[key].pop(i)
                        removed = True
                        break
                if not removed:
                    self.stats[key].pop(0)
            return value
        except ValueError:
            return "Unknown"

    def get_cpu_name(self):
        try:
            return subprocess.check_output(["lscpu"], text=True).split("Model name:")[1].strip().split("\n")[0]
        except:
            return platform.processor()

    def get_gpu_name(self):
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], text=True
            )
            return output.strip()
        except:
            return "Unknown GPU"

    def get_cpu_frequency(self):
        """
        Return a tuple of (overall CPU frequency [MHz], list of per-core frequencies).
        """
        try:
            overall_freq = int(psutil.cpu_freq().current)
            per_core_freqs = [f.current for f in psutil.cpu_freq(percpu=True)]
            return overall_freq, per_core_freqs
        except:
            return "Unknown", []

    def get_cpu_temperature(self):
        """
        Return CPU temperature via psutil.
        """
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return "Unknown"
            for name, entries in temps.items():
                if name.lower() in ["coretemp", "k10temp", "cpu-thermal"]:
                    core_readings = [temp.current for temp in entries if temp.current is not None]
                    if core_readings:
                        return sum(core_readings) / len(core_readings)
            return "Unknown"
        except Exception:
            return "Unknown"

    def get_ram_frequency(self):
        """
        Try to read RAM frequency from 'dmidecode -t 17'. 
        Returns the highest detected frequency or 'Unknown'.
        """
        now = time.time()
        if self._ram_frequency_cache is not None and now - self._ram_frequency_last_update < self._ram_frequency_refresh_s:
            return self._ram_frequency_cache

        if os.geteuid() != 0:
            return self._ram_frequency_cache or "Unknown"

        try:
            output = subprocess.check_output(
                ["dmidecode", "-t", "17"],
                text=True,
                stderr=subprocess.STDOUT,
            )
            frequencies = []
            for line in output.split("\n"):
                if "Configured Clock Speed:" in line or "Speed:" in line:
                    freq = line.split(":")[-1].strip().split(" ")[0]
                    if freq.isdigit():
                        frequencies.append(int(freq))
            if frequencies:
                self._ram_frequency_cache = max(frequencies)
                self._ram_frequency_last_update = now
                return self._ram_frequency_cache
        except Exception:
            pass

        self._ram_frequency_cache = "Unknown"
        self._ram_frequency_last_update = now
        return self._ram_frequency_cache

    def get_gpu_fan_speed_percent(self):
        """
        Uses nvidia-smi to read GPU Fan speed (percent).
        Returns int or 'Unknown'.
        """
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=fan.speed", "--format=csv,noheader,nounits"],
                text=True
            )
            return int(output.strip())
        except:
            return "Unknown"

    def build_gpu_fan_list(self):
        """
        Iteratively attempts to query GPUCurrentFanSpeedRPM for fan indices starting at 0.
        Returns a list of indices for which the query returns a valid numeric value.
        """
        fan_list = []
        idx = 0
        while True:
            try:
                rpm_out = subprocess.check_output(
                    ["nvidia-settings", "-q", f"[fan:{idx}]/GPUCurrentFanSpeedRPM"],
                    text=True
                )
                # Look for a numeric value in the output, e.g. ": 1379.".
                match = re.search(r":\s*([0-9]+)\.", rpm_out)
                if match:
                    fan_list.append(idx)
                    idx += 1
                else:
                    # If no numeric value is found, assume this index is not valid.
                    break
            except subprocess.CalledProcessError:
                # The query failed; assume no more fans exist.
                break
        return fan_list

    def get_gpu_fan_speed_rpm(self):
        """
        Uses the cached fan list (built via build_gpu_fan_list) to query GPUCurrentFanSpeedRPM.
        Returns a list of RPM values (ints) for each valid fan.
        """
        # Build and cache the fan list on first use.
        if not hasattr(self, "gpu_fan_list"):
            self.gpu_fan_list = self.build_gpu_fan_list()
        rpm_values = []
        for idx in self.gpu_fan_list:
            rpm_out = subprocess.check_output(
                ["nvidia-settings", "-q", f"[fan:{idx}]/GPUCurrentFanSpeedRPM"],
                text=True
            )
            match = re.search(r":\s*([0-9]+)\.", rpm_out)
            if match:
                rpm_values.append(int(match.group(1)))
            else:
                # If a particular fan's RPM cannot be parsed, record None or "Unknown".
                rpm_values.append("Unknown")
        return rpm_values



    def get_gpu_memory_frequency(self):
        """
        Uses nvidia-smi to read GPU Memory frequency (MHz).
        Returns int or 'Unknown'.
        """
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=clocks.mem", "--format=csv,noheader"],
                text=True
            )
            return int(output.strip().split(" ")[0])
        except:
            return "Unknown"

    def get_gpu_memory_usage(self):
        """
        Uses nvidia-smi to read GPU Memory usage (MiB).
        Returns int or 'Unknown'.
        """
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                text=True
            )
            return int(output.strip())
        except:
            return "Unknown"

    def get_gpu_memory_total(self):
        """
        Uses nvidia-smi to read GPU Memory total (MiB).
        Returns int or 'Unknown'.
        """
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                text=True
            )
            return int(output.strip())
        except:
            return "Unknown"

    def get_gpu_frequency(self):
        """
        Uses nvidia-smi to read GPU Core frequency (MHz).
        Returns int or 'Unknown'.
        """
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=clocks.gr", "--format=csv,noheader"],
                text=True
            )
            return int(output.strip().split(" ")[0])
        except:
            return "Unknown"

    def get_gpu_power(self):
        """
        Uses nvidia-smi to read GPU power (Watts).
        Returns int or 'Unknown'.
        """
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=gpu.power.draw.instant", "--format=csv,noheader,nounits"],
                text=True
            )
            return int(float(output.strip()))
        except:
            return "Unknown"

    def get_gpu_temperature(self):
        """
        Uses nvidia-smi to read the GPU temperature.
        Returns float or 'Unknown'.
        """
        try:
            output = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                text=True
            )
            return float(output.strip())
        except Exception:
            return "Unknown"

    def get_gpu_throttle_temperature(self):
        try:
            output = subprocess.check_output(
                ["nvidia-settings", "-q", "[gpu:0]/GPUSlowdownTempThreshold"],
                text=True, stderr=subprocess.PIPE  # Capture stderr for debugging
            )
            match = re.search(r":\s*([0-9]+)\.", output)
            if match:
                return int(match.group(1))
            else:
                print(f"Warning: Could not parse throttle temperature. Output: {output}")
                return "Unknown"
        except subprocess.CalledProcessError as e:
            print(f"Warning: Error getting throttle temperature: {e}")
            return "Unknown"

    def update_all(self):
        """
        Fetch the latest values for each metric and update self.stats.
        Returns a tuple or list of per-core frequencies if needed by the GUI.
        """
        # CPU Usage
        self.update_stats("CPU Usage", psutil.cpu_percent())

        # CPU Frequency and per-core frequencies
        cpu_freq, per_core_freqs = self.get_cpu_frequency()
        self.update_stats("CPU Frequency", cpu_freq)
        for i, freq in enumerate(per_core_freqs):
            self.update_stats(f"Core {i} Frequency", freq)

        # CPU Temperature
        self.update_stats("CPU Temperature", self.get_cpu_temperature())

        # RAM Usage
        self.update_stats("RAM Usage", psutil.virtual_memory().percent)

        # RAM Frequency
        self.update_stats("RAM Frequency", self.get_ram_frequency())

        # GPU Core Frequency
        self.update_stats("GPU Core Frequency", self.get_gpu_frequency())

        # GPU Power
        self.update_stats("GPU Power", self.get_gpu_power())

        # GPU Temperature
        self.update_stats("GPU Temperature", self.get_gpu_temperature())

        # GPU Memory Frequency
        self.update_stats("GPU Memory Frequency", self.get_gpu_memory_frequency())

        # GPU Memory Usage
        self.update_stats("GPU Memory Usage", self.get_gpu_memory_usage())

        # GPU Memory Total
        self.update_stats("GPU Memory", self.get_gpu_memory_total())

        # GPU Fan Speed (percent)
        self.update_stats("GPU Fan Speed", self.get_gpu_fan_speed_percent())

        # GPU Fan Speed RPM: update each fan separately using the list from the sensor
        fan_rpm = self.get_gpu_fan_speed_rpm()
        if isinstance(fan_rpm, list):
            for idx, rpm in enumerate(fan_rpm):
                self.update_stats(f"GPU Fan Speed RPM {idx}", rpm)
        else:
            self.update_stats("GPU Fan Speed RPM", fan_rpm)

        # GPU Throttle Temperature
        self.update_stats("GPU Throttle Temperature", self.get_gpu_throttle_temperature())

        return per_core_freqs
