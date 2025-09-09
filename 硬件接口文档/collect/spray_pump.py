import requests
import time
class SprayPump:
    def __init__(self):
        self.run = False
        self.spray_num = 0  # 清洗次数
        self.spray_time = 3 # 每次清洗时间，单位秒
        self.base_url = "http://192.168.1.129"
        self.interval_time = 3
        self.liquid_presence = True  # 是否为空状态
        self.freq = 1000
        self.duty = 1000
        self.mock = False  # 是否为模拟模式
        self.cleaning_volume_per_second = 2  # 每秒清洗体积，单位毫升

    def pump_switch_on(self):

        """
                设置喷淋泵为开启状态 (ifon=1)
        """
        if self.mock:
            time.sleep(3)
            return True
        try:
            url = f"{self.base_url}/pump/switch"
            params = {
                'ifon': 1,  # 1代表开启
                'freq': self.freq,
                'duty': self.duty
            }
            response = requests.get(url, params=params)
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            print(f"Error in write_info_True: {e}")
            return False

    def write_info_True(self):
        """
        喷淋控制方法
        循环喷淋直到检测到液体存在或达到指定次数
        如果 spray_num 为0，直接返回True
        每次喷淋持续 spray_time 秒，间隔 interval_time 秒
        在每次喷淋后循环检查 liquid_presence，直到为 True
        """
        if self.spray_num == 0:
            return True

        try:
            for i in range(self.spray_num):
                # 开启喷淋泵
                success = self.pump_switch_on()
                if not success:
                    return False

                # 等待喷淋时间
                time.sleep(self.spray_time)

                # 关闭喷淋泵
                success = self.write_info_False()
                if not success:
                    return False

                # 循环检查液体状态，直到检测到液体存在
                check_interval = 0.5  # 每0.5秒检查一次
                max_check_time = 50   # 最长等待50秒
                check_count = 0

                while check_count * check_interval < max_check_time:
                    if self.liquid_presence:
                        break
                    time.sleep(check_interval)
                    check_count += 1

                if not self.liquid_presence:
                    # 如果超时未检测到液体排空，返回False
                    return False


            return True

        except requests.exceptions.RequestException as e:
            print(f"Error in write_info_True: {e}")
            return False

    def write_info_False(self):
        """
        设置喷淋泵为关闭状态 (ifon=0)
        """
        try:
            url = f"{self.base_url}/pump/switch"
            params = {
                'ifon': 0,  # 0代表关闭
                'freq': self.freq,
                'duty': self.duty
            }
            response = requests.get(url, params=params)
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            print(f"Error in write_info_False: {e}")
            return False

    def calculate_cleaning_time(self,clean_volume):
        """
        根据清洗体积计算清洗时间
        :param clean_volume: 清洗体积，单位毫升
        :return: 清洗时间，单位秒
        """
        if clean_volume <= 0:
            self.spray_num = 0
        else:
            self.spray_num  = int(clean_volume / self.cleaning_volume_per_second)



# 创建全局实例

if __name__ == '__main__':
    spray_pump = SprayPump()
    spray_pump.mock = True
    spray_pump.freq = 1000
    spray_pump.duty = 1000
    spray_pump.spray_time = 3
    spray_pump.interval_time = 3
    spray_pump.liquid_presence = False
    spray_pump.calculate_cleaning_time(10)
    print(f"喷淋次数: {spray_pump.spray_num}")
    start_time = time.time()
    result = spray_pump.write_info_True()
    end_time = time.time()
    print(f"清洗结果: {result}, 总时间: {end_time - start_time} 秒")
