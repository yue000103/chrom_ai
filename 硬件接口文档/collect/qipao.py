import requests
import time


def get_bubble_status(base_url: str = "http://192.168.1.129") -> int:
    try:
        url = f"{base_url}/device/data"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json().get('data', -1)
        return -1
    except:
        return -1







if __name__ == "__main__":
    while True:
        bubble_status = get_bubble_status()
        print(f"bubble_status (decimal): {bubble_status}")
        time.sleep(2)

