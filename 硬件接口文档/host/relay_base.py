

"""
MCP23017 通用操作函数
I2C 接口: GPIO2 (SDA), GPIO3 (SCL)
功能: 提供通用的读写功能，支持实际硬件和模拟模式
"""

import time
from smbus2 import SMBus

# 1 : 低压电磁阀
# 2 : 高压电磁阀
# 3 : 气泵

# ========= MCP23017 配置 =========
I2C_BUS = 1  # 对应 /dev/i2c-1
MCP23017_ADDR = 0x20  # 默认地址，可根据 A0/A1/A2 引脚修改

# MCP23017 寄存器地址
IODIRA = 0x00   # A端口方向寄存器
IODIRB = 0x01   # B端口方向寄存器
GPIOA  = 0x12   # A端口GPIO输入
GPIOB  = 0x13   # B端口GPIO输入 (用于写时可写)
OLATB  = 0x15   # B端口输出锁存器

class MCP23017Handler:
    def __init__(self, mock_mode=False):
        """
        初始化MCP23017处理器
        
        Args:
            mock_mode (bool): 是否使用模拟模式，True为模拟模式，False为实际硬件
        """
        self.mock_mode = mock_mode
        self.current_state = 0  # 用于模拟模式记录当前状态
        
        if not self.mock_mode:
            self.bus = SMBus(I2C_BUS)
            # 配置 A 为输入, B 为输出
            self.bus.write_byte_data(MCP23017_ADDR, IODIRA, 0xFF)  # 1 = 输入
            self.bus.write_byte_data(MCP23017_ADDR, IODIRB, 0x00)  # 0 = 输出
            print("[INFO] MCP23017 配置完成: GPIOA 输入, GPIOB 输出")
    
    def write_open(self, id):
        """
        设置指定位为1，保持其他位不变
        
        Args:
            id (int): 要设置的位置(1, 2, 3等)，从右往左数的第id位
        
        Returns:
            int: 更新后的状态值
        """
        if id < 1 or id > 8:
            raise ValueError("ID必须在1到8之间")
            
        # 计算要设置的位 (从0开始，所以id-1)
        bit_position = id - 1
        bit_mask = 1 << bit_position
        
        if self.mock_mode:
            # 模拟模式下，直接修改内部状态
            self.current_state |= bit_mask
            print(f"[MOCK] 写入打开位{id}，当前状态: {self.current_state:08b}")
        else:
            # 硬件模式下，先读取当前状态，然后修改
            current = self.bus.read_byte_data(MCP23017_ADDR, OLATB)
            new_state = current | bit_mask
            self.bus.write_byte_data(MCP23017_ADDR, OLATB, new_state)
            self.current_state = new_state
            
        return self.current_state
    
    def write_close(self, id):
        """
        设置指定位为0，保持其他位不变
        
        Args:
            id (int): 要清除的位置(1, 2, 3等)，从右往左数的第id位
        
        Returns:
            int: 更新后的状态值
        """
        if id < 1 or id > 8:
            raise ValueError("ID必须在1到8之间")
            
        # 计算要清除的位
        bit_position = id - 1
        bit_mask = ~(1 << bit_position) & 0xFF  # 确保只处理低8位
        
        if self.mock_mode:
            # 模拟模式下，直接修改内部状态
            self.current_state &= bit_mask
            print(f"[MOCK] 写入关闭位{id}，当前状态: {self.current_state:08b}")
        else:
            # 硬件模式下，先读取当前状态，然后修改
            current = self.bus.read_byte_data(MCP23017_ADDR, OLATB)
            new_state = current & bit_mask
            self.bus.write_byte_data(MCP23017_ADDR, OLATB, new_state)
            self.current_state = new_state
            
        return self.current_state
    
    def read(self, id):
        """
        读取指定位的状态
        
        Args:
            id (int): 要读取的位置(1, 2, 3等)，从右往左数的第id位
        
        Returns:
            bool: 如果指定位为1返回True，否则返回False
        """
        if id < 1 or id > 8:
            raise ValueError("ID必须在1到8之间")
            
        bit_position = id - 1
        
        if self.mock_mode:
            # 模拟模式下，直接从内部状态读取
            result = bool((self.current_state >> bit_position) & 1)
            print(f"[MOCK] 读取位{id}，结果: {result}，当前状态: {self.current_state:08b}")
        else:
            # 硬件模式下，从设备读取
            state = self.bus.read_byte_data(MCP23017_ADDR, OLATB)
            self.current_state = state  # 更新内部状态记录
            result = bool((state >> bit_position) & 1)
            
        return result
    
    def close(self):
        """关闭总线连接"""
        if not self.mock_mode and hasattr(self, 'bus'):
            self.bus.close()
            print("[INFO] I2C总线已关闭")

# ========= 使用示例 =========
def main():
    # 使用实际硬件
    # handler = MCP23017Handler(mock_mode=False)
    
    # 使用模拟模式
    handler = MCP23017Handler(mock_mode=False)
    
    try:
        print("测试write_open功能:")
        handler.write_open(1)  # 设置第1位为1
        time.sleep(2)
        handler.write_open(3)  # 设置第3位为1
        time.sleep(2)
        handler.write_open(2)  # 设置第3位为1
        time.sleep(2)
        handler.write_open(4)  # 设置第3位为1
        time.sleep(2)


        
        print("\n测试read功能:")
        print(f"第1位状态: {handler.read(1)}")  # 应该为True
        print(f"第2位状态: {handler.read(2)}")  # 应该为False
        print(f"第3位状态: {handler.read(3)}")  # 应该为True
        
        print("\n测试write_close功能:")
        handler.write_close(1)  # 设置第1位为0
        time.sleep(2)

        print(f"第1位状态: {handler.read(1)}")  # 应该为False
        print(f"第3位状态: {handler.read(3)}")  # 应该仍为True
        
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        handler.close()


def interactive_test():
    handler = MCP23017Handler(mock_mode=False)  # 建议用模拟模式防止误操作硬件
    try:
        while True:
            action = input("请输入操作（1:open/2:close/exit）：").strip().lower()
            if action == "exit":
                break
            if action not in ("1", "2"):
                print("无效操作，请输入 1、2 或 exit")
                continue
            try:
                pos = int(input("请输入要操作的位置（1-8）："))
                if action == "1":
                    handler.write_open(pos)
                else:
                    handler.write_close(pos)
                print(f"第{pos}位当前状态：{handler.read(pos)}")
            except Exception as e:
                print(f"输入错误：{e}")
    finally:
        handler.close()



if __name__ == '__main__':
    # main()
    interactive_test()