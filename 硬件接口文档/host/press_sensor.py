import serial
import time
from typing import Optional


class PressureSensor:
    def __init__(self, com_port: str = "/dev/ttyAMA0", baudrate: int = 9600, timeout: float = 5.0):
        """
        Initialize the pressure sensor.
        :param com_port: Serial port, e.g. "/dev/ttyAMA2"
        :param baudrate: Baud rate, default 9600
        :param timeout: Timeout in seconds
        """
        self.com_port = com_port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_connection = None

    def connect(self) -> bool:
        """Connect to the serial port."""
        try:
            self.serial_connection = serial.Serial(
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
            print(f"Connected to {self.com_port}, baudrate: {self.baudrate}")
            return True
        except Exception as e:
            print(f"Connection failed: {str(e)}")
            return False

    def close(self):
        """Close the serial connection."""
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            print("Serial connection closed.")

    def send_command(self, hex_command: str) -> Optional[str]:
        """
        Send a command to the sensor and return the response in hex string.
        :param hex_command: Command string, e.g. "01 03 00 00 00 01 84 0A"
        :return: Response hex string or None if failed
        """
        if not self.serial_connection or not self.serial_connection.is_open:
            print("Serial connection is not open.")
            return None

        # Convert command to bytes
        try:
            cmd_bytes = bytes.fromhex(hex_command.replace(" ", ""))
        except ValueError as e:
            print(f"Invalid hex command: {str(e)}")
            return None

        # Send command
        try:
            self.serial_connection.reset_input_buffer()
            self.serial_connection.write(cmd_bytes)
            self.serial_connection.flush()
            print(f"Command sent: {hex_command.upper()}")
        except Exception as e:
            print(f"Send failed: {str(e)}")
            return None

        # Read response
        try:
            time.sleep(0.1)
            response = b""
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                if self.serial_connection.in_waiting > 0:
                    response += self.serial_connection.read(self.serial_connection.in_waiting)
                    if len(response) >= 3:
                        if len(response) >= response[2] + 5:
                            break
                time.sleep(0.01)
            if not response:
                print("No response received.")
                return None
            response_hex = response.hex().upper()
            print(f"Response: {response_hex}")
            return response_hex
        except Exception as e:
            print(f"Read failed: {str(e)}")
            return None

    def read_pressure(self) -> Optional[float]:
        """
        Read the current pressure value.
        :return: Pressure in MPa or None if failed
        """
        send_cmd = "01 03 00 00 00 01 84 0A"
        response_hex = self.send_command(send_cmd)
        if not response_hex:
            return None
        try:
            data_bytes = bytes.fromhex(response_hex)
            if len(data_bytes) < 5:
                print("Response too short.")
                return None
            if data_bytes[0] != 0x01:
                print(f"Unexpected device address: {data_bytes[0]:02X}")
                return None
            if data_bytes[1] != 0x03:
                print(f"Unexpected function code: {data_bytes[1]:02X}")
                return None
            if data_bytes[2] != 0x02:
                print(f"Unexpected data length: {data_bytes[2]:02X}")
                return None
            data_value = (data_bytes[3] << 8) | data_bytes[4]
            pressure = (1.6 * data_value) / 2000
            print(f"Raw value: {data_value}, Pressure: {pressure:.4f} MPa")
            return pressure
        except Exception as e:
            print(f"Parse failed: {str(e)}")
            return None

    def query_device_address(self) -> Optional[str]:
        """
        Query the device address.
        :return: Device address as hex string or None if failed
        """
        send_cmd = "FF 03 00 0F 00 01 A1 D7"
        response_hex = self.send_command(send_cmd)
        if not response_hex:
            return None
        try:
            data_bytes = bytes.fromhex(response_hex)
            if len(data_bytes) < 7:
                print("Response too short.")
                return None
            if data_bytes[1] != 0x03:
                print(f"Unexpected function code: {data_bytes[1]:02X}")
                return None
            if data_bytes[2] != 0x02:
                print(f"Unexpected data length: {data_bytes[2]:02X}")
                return None
            device_addr_value = (data_bytes[3] << 8) | data_bytes[4]
            device_addr = f"{device_addr_value:02X}"
            print(f"Device address: {device_addr}")
            return device_addr
        except Exception as e:
            print(f"Parse failed: {str(e)}")
            return None

    def modify_device_address(self, new_address: str) -> bool:
        """
        Modify the device address.
        :param new_address: New address as hex string, e.g. "09"
        :return: True if success, False otherwise
        """
        try:
            addr_value = int(new_address, 16)
            if not (1 <= addr_value <= 254):
                print("Address must be between 01 and FE.")
                return False
        except ValueError:
            print("Invalid address format.")
            return False
        current_addr = self.query_device_address()
        if not current_addr:
            print("Failed to get current device address.")
            return False
        current_addr_byte = int(current_addr, 16)
        new_addr_value = int(new_address, 16)
        cmd_without_crc = f"{current_addr_byte:02X} 06 00 0F 00 {new_addr_value:02X}"
        crc = self._calculate_crc16(bytes.fromhex(cmd_without_crc.replace(" ", "")))
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        send_cmd = f"{cmd_without_crc} {crc_low:02X} {crc_high:02X}"
        response_hex = self.send_command(send_cmd)
        if not response_hex:
            return False
        expected_response = send_cmd.replace(" ", "").upper()
        if response_hex == expected_response:
            print(f"Device address changed to: {new_address}")
            return True
        else:
            print("Device address change failed.")
            print(f"Expected: {expected_response}")
            print(f"Actual: {response_hex}")
            return False

    def _calculate_crc16(self, data: bytes) -> int:
        """
        Calculate Modbus RTU CRC16.
        :param data: Data to calculate CRC
        :return: CRC16 value
        """
        crc = 0xFFFF
        polynom = 0xA001
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ polynom
                else:
                    crc = crc >> 1
        return crc & 0xFFFF

    def read_multiple_pressures(self, count: int = 5, interval: float = 1.0) -> list:
        """
        Read multiple pressure values.
        :param count: Number of readings
        :param interval: Interval between readings (seconds)
        :return: List of pressure values
        """
        pressures = []
        for i in range(count):
            pressure = self.read_pressure()
            if pressure is not None:
                pressures.append(pressure)
                print(f"Reading {i + 1}: {pressure:.4f} MPa")
            else:
                print(f"Reading {i + 1}: failed")
            if i < count - 1:
                time.sleep(interval)
        return pressures

    def get_pressure_statistics(self, count: int = 10, interval: float = 0.5) -> dict:
        """
        Get statistics of multiple pressure readings.
        :param count: Number of readings
        :param interval: Interval between readings (seconds)
        :return: Statistics dictionary
        """
        pressures = self.read_multiple_pressures(count, interval)
        if not pressures:
            return {"error": "No valid pressure readings."}
        return {
            "count": len(pressures),
            "average": sum(pressures) / len(pressures),
            "min": min(pressures),
            "max": max(pressures),
            "range": max(pressures) - min(pressures),
            "values": pressures
        }

    def __del__(self):
        """Destructor to ensure serial port is closed."""
        self.close()


if __name__ == "__main__":
    # Example usage
    sensor = PressureSensor()
    if not sensor.connect():
        exit()
    try:
        print("=== Pressure Sensor Test ===\n")
        print("1. Read pressure:")
        pressure = sensor.read_pressure()
        if pressure is not None:
            print(f"   Pressure: {pressure:.4f} MPa\n")
        else:
            print("   Failed to read pressure\n")
        print("2. Query device address:")
        device_addr = sensor.query_device_address()
        if device_addr:
            print(f"   Device address: {device_addr}\n")
        else:
            print("   Failed to get device address\n")
        print("3. Read 5 pressures:")
        pressures = sensor.read_multiple_pressures(count=5, interval=1.0)
        if pressures:
            avg_pressure = sum(pressures) / len(pressures)
            print(f"   Average pressure: {avg_pressure:.4f} MPa\n")
        print("4. Get statistics for 10 readings:")
        stats = sensor.get_pressure_statistics(count=10, interval=0.5)
        if "error" not in stats:
            print(f"   Count: {stats['count']}")
            print(f"   Average: {stats['average']:.4f} MPa")
            print(f"   Min: {stats['min']:.4f} MPa")
            print(f"   Max: {stats['max']:.4f} MPa")
            print(f"   Range: {stats['range']:.4f} MPa")
        else:
            print(f"   Error: {stats['error']}")
        # # Uncomment to test address modification
        # print("\n5. Change device address from 01 to 09:")
        # if device_addr == "01":
        #     if sensor.modify_device_address("09"):
        #         print("   Device address changed successfully.")
        #     else:
        #         print("   Failed to change device address.")
    except KeyboardInterrupt:
        print("\nTest interrupted.")
    except Exception as e:
        print(f"\nError: {str(e)}")
    finally:
        sensor.close()
        print("Test finished.")
