from smbus2 import SMBus
import time

# 1 : 1号气泡传感器
# 2 : 2号气泡传感器
# 3 : 4号气泡传感器
# 4 : 3号气泡传感器
class BubbleSensor:
    def __init__(self , mock=False):
        self.bus = SMBus(1)
        self.addr = 0x20
        self.mock = mock
        self.reg = 0x12

    def read_input_state(self):
        if self.mock:
            # mock模式下直接返回全1
            return 0xFF
        return self.bus.read_byte_data(self.addr, self.reg)

    def is_bubble(self,pos):
        """
        判断第pos位（1-8，从右到左）是否为1
        :param reg: 读取的寄存器地址
        :param pos: 位置（1-8），1为最右边
        :return: True/False
        """
        if not (1 <= pos <= 8):
            raise ValueError("pos 必须为 1-8")
        state = self.read_input_state()
        return bool((state >> (pos - 1)) & 1)

if __name__ == "__main__":
    # 实际使用
    # sensor = BubbleSensor(bus, MCP23017_ADDR, mock=False)
    # mock测试
    while True:
        sensor = BubbleSensor(mock=False)
        print("1 - ",sensor.is_bubble(1),"2 - ",sensor.is_bubble(2),"3 - ",sensor.is_bubble(3),"4 - ",sensor.is_bubble(4))  # True

        print("5 - ",sensor.is_bubble(5),"6 - ",sensor.is_bubble(6),"7 - ", sensor.is_bubble(7),"8 - ", sensor.is_bubble(8))  # True
        print()
        print(" -------------------- ")

        time.sleep(2)
