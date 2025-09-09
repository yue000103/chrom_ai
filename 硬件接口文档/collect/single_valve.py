import requests


def single_valve(pin_num: int, value: int, base_url: str = "http://192.168.1.129") -> bool:

    try:
        url = f"{base_url}/device/on"
        params = {'pin_num': pin_num, 'value': value}
        response = requests.get(url, params=params, timeout=5)
        return response.status_code == 200
    except:
        return False


if __name__ == "__main__":
    success = single_valve(pin_num=15, value=0)
    print(success)

    # success = control_pump(pin_num=9, value=0)
    # print( success)

    # success = control_pump(pin_num=9, value=1)
    # print( success)