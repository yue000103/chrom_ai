import requests
import random
import time

def control_led(led_num: int, color_name: str, group_num: int) -> bool:
    """
    控制LED灯的开关状态

    Args:
        led_num (int): LED灯的编号
        color_name (str): 颜色名称 ('red' 或 'green')
        group_num (int): 组号 (0代表第一组，1代表第二组)

    Returns:
        bool: 操作是否成功
    """
    # 颜色映射
    color_map = {
        'red': 1,
        'green': 2
    }

    # 检查参数有效性
    if color_name not in color_map:
        raise ValueError("color_name must be 'red' or 'green'")
    if group_num not in [0, 1]:
        raise ValueError("group_num must be 0 or 1")
    if not isinstance(led_num, int):
        raise ValueError("led_num must be a positive integer")

    # 构建请求URL
    base_url = "http://192.168.1.129"
    url = f"{base_url}/led/on"

    # 设置请求参数
    params = {
        'led_num': led_num,
        'color_num': color_map[color_name],
        'group_num': group_num
    }

    try:
        # 发送HTTP GET请求
        response = requests.get(url, params=params)
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"Error occurred while controlling LED: {e}")
        return False

def marquee_led():
    """
    走马灯测试函数，led_num从0到19，color_name随机，group_num=0
    """
    for led_num in range(0, 20):
        color_name = random.choice(['red', 'green'])
        print(f"点亮第{led_num}号LED，颜色：{color_name}")
        control_led(led_num=led_num, color_name=color_name, group_num=0)
        time.sleep(1)  # 每次点亮间隔200ms

# 使用示例：
if __name__ == '__main__':
    # 打开第一组的第2个红色LED灯
    # success = control_led(led_num=2, color_name='red', group_num=0)
    # print(f"Operation {'successful' if success else 'failed'}")
    marquee_led()
