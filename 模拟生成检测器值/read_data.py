import math
import random
use_mock = True
def read_data_average(mock_time=0):
    if use_mock:
        # Each call represents one second passed
        mock_time += 1
        t = mock_time

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