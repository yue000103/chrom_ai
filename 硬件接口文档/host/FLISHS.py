import time
from typing import Tuple

import serial
from numpy import number


class FLISHS:
    def __init__(self, com_port: str = "/dev/ttyAMA2", baud_rate: int = 115200):
        """
        初始化FLISHS泵通信类。

        :param com_port: 串口端口名称，例如 "COM5"。
        :param baud_rate: 串口波特率，默认为 115200。
        """
        self.com = com_port
        self.port = baud_rate
        self.use_mock = False

        self.ser = self.open_serial_port()
        self.mobile_phase_inlets = '0000'

    def open_serial_port(self) -> serial.Serial | None:
        """
        打开串口。

        :return: 串口对象，如果打开失败则返回 None。
        """
        if self.use_mock:
            print("Using mock serial connection")
            return None
        try:
            ser = serial.Serial(
                self.com,
                baudrate=self.port,bytesize=serial.EIGHTBITS,  # 8 个数据位
                parity=serial.PARITY_NONE,  # 无奇偶校验
                stopbits=serial.STOPBITS_ONE,  # 1 个停止位
                timeout=1
            )
            print(f"Successfully opened port {self.com}")
            return ser
        except serial.SerialException as e:
            print(f"Could not open port {self.com}: {e}")
            return None

    def close_serial_port(self):
        """
        关闭串口。
        """
        if self.use_mock:
            print("Using mock serial connection, no port to close")
            return
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"Successfully closed port {self.com}")

    def send_command(self, command: bytes) -> bytes:
        """
        发送命令并接收响应。

        :param command: 要发送的命令。
        :return: 设备的响应。
        """
        if self.use_mock:
            print("Using mock send_command, no actual command sent")
            return b'#'
        print("send_command:",command)
        self.ser.write(command)
        response = self.ser.readline()
        print(response)
        return response

    def calculate_CRC(self, lst: list) -> str:
        """
        计算CRC校验码。

        :param lst: 要计算CRC的字节列表。
        :return: CRC校验码的ASCII字符串表示。
        """
        #记录缺少几个字符
        space_count = 12 - len(lst)

        while len(lst) < 12:
            lst.append(32)
        total = sum(lst)
        crc_value = total % 256
        crc_ascii = f"{crc_value:03}"

        # 添加相应数量的空格
        result = ' ' * space_count + crc_ascii

        return result

    def read_product_id(self) -> str | None:
        """
        读取产品ID号。

        :return: 产品ID号字符串，如果读取失败则返回 None。
        """
        return_str = ''
        command = b'!00001'
        crc = self.calculate_CRC(list(command))
        full_command = command + crc.encode() + b'\n'
        response = self.send_command(full_command)
        print(response)
        if response and response.startswith(b'!'):
            pump_type = response[4:6].decode('ascii').strip()
            product_id = response[10:12].decode('ascii').strip()
            if pump_type == '01':
                return_str = return_str + '泵类型：四元泵'
            elif pump_type == '00':
                return_str = return_str + '泵类型：四元泵'
            else:
                return_str = return_str + '泵类型：不知'
            return_str = return_str + '  设备ID：' + product_id
            return return_str
        else:
            return None

    def read_pump_status(self, id: int) -> tuple[float, float] | tuple[None, None]:
        """
        读取泵状态。

        :param id: 泵的标识，0表示A泵，1表示B泵。
        :return: 一个元组，包含泵的状态（运行或停止）和当前流量（ml/min），如果读取失败则返回 (None, None)。
        """
        command = b'!FA004'
        crc = self.calculate_CRC(list(command))
        full_command = command + crc.encode() + b'\n'
        response = self.send_command(full_command)
        if response and response.startswith(b'!'):
            if id == 0:
                status = 1 if int(response[5]) == 1 else 0
                flow_rate = int(response[6:12].decode('ascii').strip(), 10) / 100
                return status, flow_rate
            elif id == 1:
                status = 1 if int(response[12]) == 1 else 0
                flow_rate = int(response[13:19].decode('ascii').strip(), 10) / 100
                return status, flow_rate
            else:
                return None, None
        else:
            return None, None



    def read_pump_error_code(self) -> str | None:
        """
        读取泵错误码。

        :return: 泵错误码字符串，如果读取失败则返回 None。
        """
        command = b'!FA00553'
        crc = self.calculate_CRC(list(command))
        full_command = command + crc.encode() + b'\n'
        response = self.send_command(full_command)
        if response and response.startswith(b'!'):
            error_code = response[5:11].decode('ascii').strip()
            return error_code
        else:
            return None

    def write_speed(self, flow_rate: float) -> bool:
        """
        设定输液泵流量。
        :param flow_rate: 要设定的流量，单位为 ml/min。
        :ai: 泵的标识，0表示A泵，1表示B泵。
        :return: 设定是否成功。
        """
        flow_rate_hex = f"{int(flow_rate * 100)}".rjust(6)
        command = b'!FA010' + flow_rate_hex.encode()
        crc = self.calculate_CRC(list(command))
        full_command = command + crc.encode() + b'\n'
        response = self.send_command(full_command)
        return response == b'#'

    def set_pump_pressure_limits(self, upper_limit: float, lower_limit: float, ai: int = 0) -> bool:
        """
        设定泵压力上下限。

        :param upper_limit: 压力上限，单位为 Mpa。
        :param lower_limit: 压力下限，单位为 Mpa，必须低于上限。
        :param ai: 泵的标识，0表示A泵，1表示B泵。
        :return: 设定是否成功。
        """
        upper_limit_hex = f"{int(upper_limit * 100):03X}"
        lower_limit_hex = f"{int(lower_limit * 100):03X}"
        command_upper = b'!FA013' + (b'0' if ai == 0 else b'1') + upper_limit_hex.encode() + b'56'
        command_lower = b'!FA014' + (b'0' if ai == 0 else b'1') + lower_limit_hex.encode() + b'57'
        crc_upper = self.calculate_CRC(list(command_upper))
        crc_lower = self.calculate_CRC(list(command_lower))
        full_command_upper = command_upper + crc_upper.encode() + b'\n'
        full_command_lower = command_lower + crc_lower.encode() + b'\n'
        self.send_command(full_command_upper)
        self.send_command(full_command_lower)
        response_upper = self.ser.read(1)
        response_lower = self.ser.read(1)
        return response_upper == b'#' and response_lower == b'#'

    def switch_start(self, auto_stop_time: int = 0) -> bool:
        """
        启动泵。

        :ai: 泵的标识，0表示A泵，1表示B泵。
        :param auto_stop_time: 自动停止时间，单位为秒（50ms * auto_stop_time）。
        :return: 启动是否成功。
        """
        command = b'!FA015' + f"{auto_stop_time}".rjust(6).encode()
        crc = self.calculate_CRC(list(command))
        full_command = command + crc.encode() + b'\n'
        response = self.send_command(full_command)
        return response == b'#'

    def switch_stop(self) -> bool:
        """
        停止泵。

        :ai: 泵的标识，0表示A泵，1表示B泵。
        :return: 停止是否成功。
        """
        command = b'!FA016'
        crc = self.calculate_CRC(list(command))
        full_command = command + crc.encode() + b'\n'
        response = self.send_command(full_command)
        return response == b'#'

    def select_mobile_phase_inlets(self, inlets: str) -> bool:
        """
        选择流动相入口。

        :param inlets: 流动相入口的二进制标识，例如 1001 表示 S4 和 S1 开启。
        :return: 选择是否成功。
        """

        decimal_value = int(inlets, 2)
        print(decimal_value)

        inlets_hex = hex(decimal_value)[2:].upper()
        print(inlets_hex)

        self.mobile_phase_inlets = inlets

        print(inlets_hex)
        command = b'!FA012' + f"{inlets_hex}".rjust(6).encode()
        # command = b'!FA012     7'
        crc = self.calculate_CRC(list(command))
        full_command = command + crc.encode() + b'\n'
        response = self.send_command(full_command)
        return response == b'#'

    def count_ones(self):
        return self.mobile_phase_inlets.count('1')  # 计算 '1' 出现的次数

    def set_mobile_phase_proportions(self ,proportions: list[float]):
        """
        设定流动相比例。

        :ai: 泵的标识，0表示A泵，1表示B泵。
        :param proportions: 流动相比例列表，包含两个0到100之间的整数，表示流动相的比例百分比。
        :return: 设定是否成功。
        """
        command = []
        response = []
        if sum(proportions) != 100:
            print("Error: The sum of the mobile phase proportions must be 100%.")
            return False
        proportions_hex = [f"{hex(int(proportion * 10))[2:]}" for proportion in proportions]
        proportions_hex = [value.zfill(3).upper() for value in proportions_hex]
        command.append(b'!FA011' + proportions_hex[0].encode() + proportions_hex[1].encode() )
        command.append(b'!FA111' + proportions_hex[2].encode() + proportions_hex[3].encode() )

        for i in range(2):

            crc = self.calculate_CRC(list(command[i]))

            full_command = command[i] + crc.encode() + b'\n'

            response.append(self.send_command(full_command) == b'#')

        if all(response):
            return True
        else:
            # 返回第一个不为 True 的下标
            return next(index for index, value in enumerate(response) if not value)

if __name__ == '__main__':
    fi = FLISHS()
    product_id = fi.read_product_id()
    print(product_id)
    fi.write_speed(100)


    fi.select_mobile_phase_inlets('1100')
    res = fi.set_mobile_phase_proportions([0,75,25,0])
    print(res)

    fi.switch_start(0)
    status, flow_rate = fi.read_pump_status(0)
    print("id = 0 ","status:", status, "flow_rate:", flow_rate)
    status, flow_rate = fi.read_pump_status(1)
    print("id = 1 ","status:", status, "flow_rate:", flow_rate)

    time.sleep(15)
    fi.switch_stop()
    pass