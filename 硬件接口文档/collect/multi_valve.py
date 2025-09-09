import time

import requests


def switch_valve(num: int, valve_num: str, base_url: str = "http://192.168.1.129") -> bool:
    try:
        url = f"{base_url}/valve/switch"
        params = {'num': num, 'valve_num': valve_num}
        response = requests.get(url, params=params, timeout=5)
        return response.status_code == 200
    except:
        return False


if __name__ == "__main__":
    i = 0
    while True:
        i = i + 1
        success = switch_valve(i, A)
        print(success)
        time.sleep(2)
        if i == 10:
            i = 0
