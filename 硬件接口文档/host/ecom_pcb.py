import serial
import time
from datetime import datetime
import math
import random

def get_current_time():
    now = datetime.now()
    result = now.strftime("%Y-%m-%d %H:%M:%S")
    return result


# Data collection sequence: Read lamp status -> Turn on lamp -> Start subscription -> Read data once

# ABu: Stop subscription
# ABs: Start subscription
# ABr: Read once
# LPw: Turn on lamp
# LPr: Read lamp status
# ZRw: Auto zero
# ZRr: Check zeroing status
# SGw: Generate sound 1 = 2300 Hz, length 2 ms, 2 = 2300 Hz, length 50 ms, 3 = 2300 Hz, length 200 ms
# DHr: Query remote control disable timeout status
# DHw: Disable remote control mode timeout
# HCw: Refresh remote control mode timer
# DHw T: Disable timeout, F: Set timeout
# SFw: Set acquisition frequency 01 02 03 04 05
# WLr: Query wavelength of each channel
# WLw: Set wavelength of each channel, e.g.: WLwA240B360
# WSr: Query scan wavelength range
# WSw: Set wavelength range, e.g.: WSwX340Y480

class UVDetector:
    def __init__(self, com_port: str = "/dev/ttyAMA3", baudrate: int = 57600, timeout: float = 5):
        """
        Initialize UV detector serial communication class.

        :param com_port: Serial device path, e.g. "/dev/ttyAMA2"
        :param baudrate: Baud rate, default 9600
        :param timeout: Read/write timeout (seconds)
        """
        self.com_port = com_port
        self.baudrate = baudrate
        self.timeout = timeout
        self.use_mock = False


        self.serial_connection = self.open_serial()
        self.collect_datas = []
        self._mock_time = 0

    def open_serial(self):
        if self.use_mock:
            print("Using mock serial connection")
            return
        try:
            ser = serial.Serial(
                port=self.com_port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False
            )
            print(f"Successfully connected to serial port {self.com_port}")
            self.serial_connection = ser
            self.open_light()
            self.start_collect()
            return ser
        except Exception as e:
            print(f"Serial connection failed: {str(e)}")
            return None



    def close_serial(self):
        """
        Close the serial connection.
        """
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            print(f"Serial connection to {self.com_port} closed")

    def send_command(self, command: str) -> str | None:
        """
        Send a command and receive the response.

        :param command: Command string to send
        :return: Device response string, None if failed
        """
        if not self.serial_connection or not self.serial_connection.is_open:
            print("Serial connection is not available")
            return None

        try:
            # Clear input buffer
            self.serial_connection.reset_input_buffer()

            # Send command
            full_command = f"{command}\n\r".encode('utf-8')
            print("Sending command:", full_command.decode('utf-8'))
            self.serial_connection.write(full_command)

            # Wait and receive response
            time.sleep(0.1)  # Give the device some time to process the command

            # Read response
            response = ""
            start_time = time.time()

            while time.time() - start_time < self.timeout:
                if self.serial_connection.in_waiting > 0:
                    response += self.serial_connection.read(self.serial_connection.in_waiting).decode('utf-8')
                    # If a complete response is received (adjust end condition according to actual protocol)
                    print("response",response)
                    if response.endswith('\n') or response.endswith('\r\n'):
                        break
                time.sleep(0.01)

            response = response.strip()
            print("Received response:", response)
            return response

        except Exception as e:
            print(f"Command execution failed: {str(e)}")
            return None

    def query_device_status(self, command):
        if self.use_mock:
            print(f"Mock command: {command}")
            return "Mock response for command: " + command
        full_command = f"#{command}"
        return self.send_command(full_command)


    def build_auto_zero_command(self):
        self.query_device_status('ZRwT')

    def start_collect(self):
        self.query_device_status('ABs')

    def open_light(self):
        response = self.query_device_status("LPr")
        # Parse the response and check if the lamp was turned on successfully
        if response and "F" in response:
            self.query_device_status('LPwT')

    def test(self, command):
        return self.query_device_status(command)

    def read_data_average(self):
        if self.use_mock:
            # Each call represents one second passed
            self._mock_time += 1
            t = self._mock_time

            # Baseline drift (slow)
            baseline = 1 + 0.0005 * t

            # Three Gaussian peaks
            # At 4 min, height 20, width 1 min
            peak1 = 20 * math.exp(-((t - 4 * 60) ** 2) / (2 * (60) ** 2))
            # At 25 min, height 50, width 2.5 min
            peak2 = 50 * math.exp(-((t - 7 * 60) ** 2) / (2 * (150) ** 2))
            # At 45 min, height 30, width 2 min
            peak3 = 30 * math.exp(-((t - 12 * 60) ** 2) / (2 * (120) ** 2))

            # Small random noise
            noise = random.gauss(0, 0.2)

            value = baseline + peak1 + peak2 + peak3 + noise
            return round(value, 5)


        response = self.query_device_status('ABr')

        if response:
            a_part, b_part  = self.parse_collect_data(response)
            return a_part
        else:
            return 500

    def parse_collect_data(self, data):
        """
        Parse the data string to extract a_val and b_val.
        If parsing fails, return None and log the error message.

        :param data: Input string data
        :return: (a_val, b_val) or None
        """
        try:
            # Extract data part
            data_str = data[3:]

            # Find and extract A and B data segments
            index = data_str.find('A')
            if index == -1:
                raise ValueError("ECOM: Marker 'A' not found in data")

            a_val = data_str[index:data_str.find('B')]
            b_val = data_str[data_str.find('B'):]

            # Convert A and B values to float
            a_val = float(a_val[1:a_val.find(':')]) / 100000
            b_val = float(b_val[1:b_val.find(':')]) / 100000

            return a_val, b_val

        except (ValueError, IndexError) as e:
            # Catch conversion and index errors
            print(f"ECOM: Failed to parse data: {e}")
            return None

    def parse_wavelength_data(self,data: str):
        """
        解析波长数据字符串，返回A和B通道的波长数值
        :param data: 形如 'WLrA270B271' 的字符串
        :return: (a_wavelength, b_wavelength)
        """
        print("parse_wavelength_data",data)
        try:
            a_index = data.index('A') + 1
            b_index = data.index('B') + 1
            a_wavelength = int(data[a_index:b_index - 1])
            b_wavelength = int(data[b_index:])
            return a_wavelength, b_wavelength
        except (ValueError, IndexError):
            print("数据格式错误，无法解析")
            return None, None

    def read_wavelength(self):
        all_wavelength = self.query_device_status('WLr')
        time.sleep(0.1)

        if not all_wavelength:
            print("读取波长失败")
            return 0, 0
        a_val, b_val = self.parse_wavelength_data(all_wavelength)
        return a_val, b_val


    def set_wavelength(self, a_wavelength: int = 271, b_wavelength: int = 271) -> bool:
        """
        设置A、B通道波长并验证是否设置成功
        :param a_wavelength: A通道波长，默认271
        :param b_wavelength: B通道波长，默认271
        :return: 设置成功返回True，否则False
        """
        # 发送设置命令
        command = f"WLwA{a_wavelength}B{b_wavelength}"
        set_response = self.query_device_status(command)
        if set_response is None:
            print("设置命令发送失败")
            return False


        # 解析波长
        a_val, b_val = self.read_wavelength()
        if a_val == a_wavelength and b_val == b_wavelength:
            print(f"波长设置成功: A={a_val}, B={b_val}")
            return True
        else:
            print(f"波长设置失败: 期望A={a_wavelength},B={b_wavelength}，实际A={a_val},B={b_val}")
            return False

    def parse_wavelength_range(self,data: str):
        """
        解析波长范围字符串，返回X和Y的数值
        :param data: 形如 'WSrX220Y380' 的字符串
        :return: (x_wavelength, y_wavelength)
        """
        try:
            x_index = data.index('X') + 1
            y_index = data.index('Y') + 1
            x_wavelength = int(data[x_index:y_index - 1])
            y_wavelength = int(data[y_index:])
            return x_wavelength, y_wavelength
        except (ValueError, IndexError):
            print("数据格式错误，无法解析")
            return None, None

    def read_wavelength_range(self):
        wavelength_range = self.query_device_status('WSr')
        print("read_wavelength_range",type(wavelength_range))
        time.sleep(0.1)
        if not wavelength_range:
            print("读取波长失败")
            return 0, 0
        x_wavelength, y_wavelength = self.parse_wavelength_range(wavelength_range)
        return x_wavelength, y_wavelength


    def set_wavelength_range(self, x_wavelength: int = 220, y_wavelength: int = 220) -> bool:
        """
        设置A、B通道波长并验证是否设置成功
        :param a_wavelength: A通道波长，默认271
        :param b_wavelength: B通道波长，默认271
        :return: 设置成功返回True，否则False
        """
        # 发送设置命令
        command = f"WSwX{x_wavelength}Y{y_wavelength}"
        set_response = self.query_device_status(command)
        if set_response is None:
            print("设置命令发送失败")
            return False


        # 解析波长
        x, y = self.read_wavelength_range()
        if x == x_wavelength and y == y_wavelength:
            print(f"波长范围设置成功: X={x}, Y={y}")
            return True
        else:
            print(f"波长设置失败: 期望X={x_wavelength}, Y={y_wavelength}，实际X={x},Y={y}")
            return False


    def __del__(self):
        """Destructor to ensure the serial port is properly closed"""
        self.close_serial()

if __name__ == '__main__':
    # Initialize UV detector with serial communication
    uv = UVDetector()


    # while input("Continue? (y/n): ") != 'n':
    #     command = input("Please enter command:")
    #     if command == 'ABr':
    #         response = uv.read_data_average()
    #         print(response)
    #
    #     else:
    #         uv.test(command)
    uv.set_wavelength_range(300, 400)

    time.sleep(2)
    uv.set_wavelength(360, 260)


    # uv.start_collect()
    #
    # data_a = uv.read_data_average()
    # print(data_a)
    # while True:
    #     data_a = uv.read_data_average()
    #     print(data_a)
    #     time.sleep(1)
    # uv.collect_data()

    # uv.query_wavelength_range()
    # uv.clear_zero()

    # Close serial port
    uv.close_serial()
