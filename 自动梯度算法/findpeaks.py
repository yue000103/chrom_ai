import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl
from collections import deque
from scipy.signal import savgol_filter
import time

# 解决中文显示问题
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
mpl.use('TkAgg')  # 使用TkAgg后端以支持中文显示


class GradientElutionController:
    """
    动态梯度洗脱控制器 - 基础版
    用于控制液相色谱中的梯度洗脱过程，通过监测信号峰来动态调整洗脱条件
    """

    def __init__(self, start_ratio=100, end_ratio=50, n1_volumes=2,
                 gradient_rate=5.0, peak_threshold=0.1, column_volume=1.0,
                 peak_hold_signal_threshold=None):
        """
        初始化梯度洗脱控制器

        :param start_ratio: 起始洗脱比例(%)，默认100，值越高表示起始洗脱剂A比例越高
        :param end_ratio: 结束洗脱比例(%)，默认50，表示梯度结束时的目标比例
        :param n1_volumes: 初始恒定阶段的柱体积数，默认2，增大会延长初始平衡阶段
        :param gradient_rate: 梯度变化速率(%/CV)，默认5，值越大梯度越陡
        :param peak_threshold: 峰检测阈值，默认0.1，降低可提高灵敏度但可能增加假阳性
        :param column_volume: 色谱柱体积(mL)，默认1.0，用于计算洗脱体积
        :param peak_hold_signal_threshold: 峰保持信号阈值，默认为峰检测阈值的1.5倍
        """
        # 梯度洗脱参数
        self.START_RATIO = start_ratio
        self.END_RATIO = end_ratio
        self.N1_VOLUMES = n1_volumes
        self.GRADIENT_RATE = gradient_rate
        self.PEAK_THRESHOLD = peak_threshold
        self.COLUMN_VOLUME = column_volume
        # 新增参数：peak hold信号强度阈值
        self.PEAK_HOLD_SIGNAL_THRESHOLD = peak_hold_signal_threshold or (peak_threshold * 1.5)
        self.use_signal_threshold = False if peak_hold_signal_threshold is None else True

        # 状态变量
        self.current_ratio = start_ratio
        self.current_volume = 0
        self.last_gradient_update_volume = 0
        self.state = "initial_hold"  # 控制状态：初始恒定阶段
        self.peak_detected = False  # 是否检测到峰
        self.peak_start_volume = 0  # 峰起始体积
        self.peak_end_volume = 0  # 峰结束体积
        self.previous_state = None  # 手动hold前的状态
        self.manual_hold_enabled = False  # 手动hold标志

        # 缓存大小常量
        self.SIGNAL_BUFFER_SIZE = 50
        self.BASELINE_BUFFER_SIZE = 200

        # 数据缓存
        self.signal_buffer = deque(maxlen=self.SIGNAL_BUFFER_SIZE)  # 信号缓存，用于峰检测
        self.baseline_buffer = deque(maxlen=self.BASELINE_BUFFER_SIZE)  # 基线缓存，用于估算背景噪声

        # 统计信息
        self.detected_peaks = []  # 检测到的峰列表
        self.total_peaks = 0  # 峰计数器

    def set_current_ratio(self, new_ratio):
        """
        手动设置当前溶剂比例

        :param new_ratio: 新的溶剂比例(百分比)
        :return: 更新后的当前比例
        """
        # 确保比例在合理范围内
        new_ratio = max(self.END_RATIO, min(self.START_RATIO, new_ratio))
        self.current_ratio = new_ratio
        # 更新时间点，避免突然梯度变化
        self.last_gradient_update_volume = self.current_volume
        return self.current_ratio

    def set_gradient_rate(self, new_rate):
        """
        调整梯度下降速率

        :param new_rate: 新的梯度下降速率(%/CV)
        :return: 更新后的梯度速率
        """
        if new_rate > 0:
            self.GRADIENT_RATE = new_rate
        return self.GRADIENT_RATE



    def set_manual_hold(self, hold_enabled=True):
        """
        启用或禁用手动保持模式

        :param hold_enabled: 布尔值，是否启用手动保持
        :return: 当前状态
        """
        if hold_enabled and not self.manual_hold_enabled:
            self.previous_state = self.state  # 保存当前状态
            self.manual_hold_enabled = True
            self.state = "manual_hold"
        elif not hold_enabled and self.manual_hold_enabled:
            # 恢复之前的状态
            self.manual_hold_enabled = False
            self.state = self.previous_state if self.previous_state else "gradient"
            self.last_gradient_update_volume = self.current_volume  # 重置梯度更新时间点

        return self.state

    def update_signal(self, signal_value, volume_increment=0.02):
        """
        更新信号并处理峰检测和梯度调整

        :param signal_value: 当前检测器读数，表示色谱信号强度
        :param volume_increment: 每次更新的体积增量(mL)，默认0.02，影响采样频率
        :return: 包含当前状态信息的字典
        """
        self.current_volume += volume_increment
        self.signal_buffer.append(signal_value)
        peak_status = self.detect_peak(signal_value)
        # 将signal_value传递给update_gradient
        self.update_gradient(peak_status, signal_value)

        return {
            'volume': self.current_volume,
            'ratio': self.current_ratio,
            'signal': signal_value,
            'state': self.state,
            'peak_detected': peak_status,
            'threshold': self.PEAK_THRESHOLD,
            'peak_hold_threshold': self.PEAK_HOLD_SIGNAL_THRESHOLD
        }

    def detect_peak(self, signal_value):
        """
        基础峰检测算法

        :param signal_value: 当前信号值
        :return: 布尔值，表示是否检测到峰
        """
        # 常量定义
        MIN_POINTS_FOR_DETECTION = 10
        PERCENTILE_FOR_BASELINE = 10
        MIN_BASELINE_POINTS = 50
        TREND_WINDOW = 5
        PEAK_END_THRESHOLD_FACTOR = 0.5

        # 数据点不足时不进行检测
        if len(self.signal_buffer) < MIN_POINTS_FOR_DETECTION:
            return False

        # 计算基线估计值
        baseline = np.percentile(list(self.baseline_buffer), PERCENTILE_FOR_BASELINE) if len(
            self.baseline_buffer) > MIN_BASELINE_POINTS else signal_value
        self.baseline_buffer.append(signal_value)

        # 计算信号相对于基线的强度
        signal_intensity = signal_value - baseline

        # 未检测到峰状态下检查 是否有峰起始
        if not self.peak_detected:
            if (signal_intensity > self.PEAK_THRESHOLD and
                    len(self.signal_buffer) >= TREND_WINDOW and
                    self.signal_buffer[-1] > self.signal_buffer[-3] > self.signal_buffer[-5]):
                self.peak_detected = True
                self.peak_start_volume = self.current_volume
                return True
        else:
            # 已在峰状态下检查峰是否结束
            if (signal_intensity < self.PEAK_THRESHOLD * PEAK_END_THRESHOLD_FACTOR and
                    len(self.signal_buffer) >= TREND_WINDOW and
                    self.signal_buffer[-1] < self.signal_buffer[-3] < self.signal_buffer[-5]):
                self.peak_detected = False
                self.peak_end_volume = self.current_volume
                self._record_peak()
                return False
            return True

        return False

    def _record_peak(self):
        """
        记录检测到的峰信息
        """
        peak_width = self.peak_end_volume - self.peak_start_volume
        self.detected_peaks.append({
            'start': self.peak_start_volume,
            'end': self.peak_end_volume,
            'width': peak_width
        })
        self.total_peaks += 1

    def update_gradient(self, peak_status, signal_value):
        """
        根据当前状态和峰检测结果更新洗脱梯度

        :param peak_status: 布尔值，表示当前是否检测到峰
        :param signal_value: 当前信号值
        """
        # 添加调试信息，更清晰地显示状态转换
        # print(f"状态: {self.state}, 峰检测: {peak_status}, 信号: {signal_value:.5f}, "
        #       f"阈值: {self.PEAK_THRESHOLD:.5f}, Peak Hold阈值: {self.PEAK_HOLD_SIGNAL_THRESHOLD:.5f}")

        # 手动hold优先级最高
        if self.manual_hold_enabled:
            self.state = "manual_hold"
            return

        # 计算当前体积相对于柱体积的比值
        volume_in_column_volumes = self.current_volume / self.COLUMN_VOLUME

        # 初始恒定阶段逻辑
        if self.state == "initial_hold":
            if volume_in_column_volumes >= self.N1_VOLUMES:
                self.state = "gradient"
                self.last_gradient_update_volume = self.current_volume

        # 梯度阶段逻辑
        elif self.state == "gradient":
            # 检测到峰且信号超过peak_hold阈值，暂停梯度变化
            if peak_status and signal_value >= self.PEAK_HOLD_SIGNAL_THRESHOLD and self.use_signal_threshold:
                self.state = "peak_hold"
                print(f"进入peak_hold状态，信号强度: {signal_value:.5f} > {self.PEAK_HOLD_SIGNAL_THRESHOLD:.5f}")
                return

            # 正常梯度变化 - 每次更新时直接计算变化量
            volume_passed_cv = (self.current_volume - self.last_gradient_update_volume) / self.COLUMN_VOLUME
            if volume_passed_cv > 0:  # 只要有体积变化就更新梯度
                # 更新梯度前记录当前体积点
                self.last_gradient_update_volume = self.current_volume
                # 计算新比例 - 变化量与经过的柱体积成正比
                new_ratio = self.current_ratio - self.GRADIENT_RATE * volume_passed_cv
                # 限制在终止比例范围内
                self.current_ratio = max(self.END_RATIO, new_ratio)
                if self.current_ratio <= self.END_RATIO:
                    self.state = "finished"

        # 峰保持阶段逻辑
        elif self.state == "peak_hold":
            if not peak_status:
                # 峰结束，记录当前体积作为梯度继续变化的起始点
                self.state = "gradient"
                self.last_gradient_update_volume = self.current_volume
                print(f"退出peak_hold状态，恢复梯度变化，当前体积: {self.current_volume:.2f}")

    def set_peak_hold_threshold(self, new_threshold, enable=True):
        """
        设置peak hold的信号强度阈值并启用/禁用功能

        :param new_threshold: 新的信号强度阈值
        :param enable: 是否启用peak hold功能
        :return: 更新后的阈值
        """
        if new_threshold > 0:
            self.PEAK_HOLD_SIGNAL_THRESHOLD = new_threshold

        # 添加启用/禁用功能的控制
        self.peak_hold_enabled = enable
        print(f"Peak Hold功能: {'启用' if enable else '禁用'}, 阈值: {self.PEAK_HOLD_SIGNAL_THRESHOLD}")

        return self.PEAK_HOLD_SIGNAL_THRESHOLD

class PrepChromController(GradientElutionController):
    """
    制备色谱控制器 - 优化版动态阈值算法
    继承基础控制器，添加更高级的信号处理和峰检测算法
    """

    def __init__(self, start_ratio=100, end_ratio=50, n1_volumes=2,
                 gradient_rate=5.0, peak_threshold=0.08, column_volume=1.0,
                 sg_window=21, sg_order=2, baseline_window=200, k_factor=2.5,
                 peak_hold_signal_threshold=None):
        """
        初始化制备色谱控制器

        :param start_ratio: 起始洗脱比例(%)，默认100
        :param end_ratio: 结束洗脱比例(%)，默认50
        :param n1_volumes: 初始恒定阶段的柱体积数，默认2
        :param gradient_rate: 梯度变化速率(%/CV)，默认5
        :param peak_threshold: 峰检测阈值，默认0.08，比基础版更灵敏
        :param column_volume: 色谱柱体积(mL)，默认1.0
        :param sg_window: Savitzky-Golay滤波窗口大小，默认21，必须为奇数
        :param sg_order: Savitzky-Golay滤波多项式阶数，默认2，必须小于窗口大小
        :param baseline_window: 基线估计窗口大小，默认200，增大提高基线稳定性
        :param k_factor: 阈值系数，默认2.5，增大降低灵敏度，减小提高灵敏度
        :param peak_hold_signal_threshold: 峰保持信号强度阈值，默认为peak_threshold的2倍
        """
        # 调用父类初始化，传入peak_hold_signal_threshold
        super().__init__(start_ratio, end_ratio, n1_volumes, gradient_rate,
                         peak_threshold, column_volume,
                         peak_hold_signal_threshold or (peak_threshold * 2.0))

        self.current_peak_tubes_intid = []
        self.int_tube_id_now = 0
        self.tubes_list = []
        self.tube_index_now = None
        self.current_peak_tubes = list()

        # 信号处理参数
        self.SG_WINDOW = sg_window if sg_window % 2 == 1 else sg_window + 1
        self.SG_ORDER = min(sg_order, sg_window - 1)
        self.BASELINE_WINDOW = baseline_window
        self.K_FACTOR = k_factor

        # 最小基线标准差 - 防止噪声过低时过度敏感
        self.MIN_BASELINE_STD = 0.003

        # 峰检测阈值参数
        self.SENSITIVE_THRESHOLD_FACTOR = 0.7  # 灵敏阈值系数
        self.PEAK_END_THRESHOLD_FACTOR = 1.5  # 峰终止阈值系数

        # 趋势判断参数
        self.TREND_WINDOW = 5  # 趋势判断窗口
        self.SHORT_TREND_WINDOW = 3  # 短期趋势窗口
        self.FALLING_TREND_THRESHOLD = 0.7  # 下降趋势阈值

        # 信号差值判断参数
        self.SIGNAL_DIFF_FACTOR = 2.0  # 信号差值系数

        # 基线更新参数
        self.BASELINE_UPDATE_ALPHA = 0.05  # 基线更新率
        self.SLOPE_THRESHOLD = 0.2  # 斜率阈值
        self.VARIATION_THRESHOLD = 0.8  # 变异阈值
        self.BASELINE_DISTANCE_THRESHOLD = 1.2  # 基线距离阈值

        # 峰检测参数
        self.MIN_PEAK_WIDTH = 8  # 最小峰宽度(点数)
        self.POST_PEAK_BUFFER_SIZE = 5  # 峰后缓冲区大小

        # 缓存设置
        self.RAW_BUFFER_SIZE = 1000
        self.SMOOTHED_BUFFER_SIZE = 100
        self.PEAK_START_BUFFER_SIZE = 50

        # 信号缓存优化
        self.raw_buffer = deque(maxlen=self.RAW_BUFFER_SIZE)
        self.smoothed_buffer = deque(maxlen=self.SMOOTHED_BUFFER_SIZE)

        # 基线估计系统
        self.baseline_estimator = deque(maxlen=self.BASELINE_WINDOW)
        self.current_baseline = peak_threshold
        self.baseline_std = 0.01  # 基线标准差初始值

        # 峰检测状态跟踪
        self.peak_start_buffer = deque(maxlen=self.PEAK_START_BUFFER_SIZE)  # 峰起始部分信号缓存

        # 峰后缓冲计数器
        self.post_peak_buffer = 0  # 峰后缓冲区计数，防止峰尾干扰基线估计

        # 鞍点检测参数
        self.enable_saddle_detection = False  # 默认关闭鞍点检测
        self.SADDLE_WINDOW = 15  # 鞍点检测窗口大小
        self.SADDLE_SIGNIFICANCE = 1.5  # 鞍点显著性因子
        self.SADDLE_CONFIRM_COUNT = 3  # 连续检测到鞍点的次数阈值
        self.saddle_candidate_count = 0  # 当前连续检测到鞍点的次数
        self.saddle_detected = False  # 是否已检测到鞍点
        self.last_saddle_volume = 0  # 最后一个鞍点的体积位置
        self.detected_saddles = []  # 检测到的鞍点列表

    def update_baseline(self, smoothed_value):
        """
        更新基线估计

        :param smoothed_value: 平滑后的信号值
        """
        # 峰后缓冲区处理 - 峰后不立即更新基线，避免峰尾干扰
        if not self.peak_detected and self.post_peak_buffer > 0:
            self.post_peak_buffer -= 1
            return

        # 只在非峰状态下更新基线
        if not self.peak_detected:
            # 仅当有足够的历史数据时进行复杂判断
            if len(self.smoothed_buffer) >= self.SHORT_TREND_WINDOW + 4:
                # 获取最近的信号数据进行分析
                recent = list(self.smoothed_buffer)[-(self.SHORT_TREND_WINDOW + 4):]
                # 计算斜率和波动情况
                recent_slope = (recent[-1] - recent[0]) / (self.SHORT_TREND_WINDOW + 3)
                recent_variation = np.std(recent)

                # 三重条件：1.无明显上升 2.波动小 3.值接近当前基线
                if (abs(recent_slope) < self.SLOPE_THRESHOLD * self.baseline_std and
                        recent_variation < self.VARIATION_THRESHOLD * self.baseline_std and
                        abs(smoothed_value - self.current_baseline) < self.BASELINE_DISTANCE_THRESHOLD * self.baseline_std):

                    # 使用超低alpha值进行缓慢更新
                    self.current_baseline = self.BASELINE_UPDATE_ALPHA * smoothed_value + (
                                1 - self.BASELINE_UPDATE_ALPHA) * self.current_baseline

                    # 仅将稳定区域的值加入基线统计队列
                    self.baseline_estimator.append(smoothed_value)

                    # 每20个点更新一次噪声统计
                    if len(self.baseline_estimator) % 20 == 0 and len(self.baseline_estimator) > 30:
                        # 计算基线标准差，用于动态阈值设定
                        baseline_values = list(self.baseline_estimator)
                        std_value = np.std(baseline_values)
                        # 确保最小噪声水平，防止过度敏感
                        self.baseline_std = max(std_value, self.MIN_BASELINE_STD)
            else:
                # 初始化阶段直接设置基线
                if len(self.baseline_estimator) < 5:
                    self.current_baseline = smoothed_value
                    self.baseline_estimator.append(smoothed_value)

    def _record_peak(self, is_saddle_end=False):
        """
        记录检测到的峰信息

        :param is_saddle_end: 是否由鞍点结束此峰
        """

        print('record peak:', self.peak_start_volume, self.current_volume, is_saddle_end)
        if is_saddle_end:
            peak_end_volume = self.current_volume
            end_reason = "saddle"  # 峰由鞍点终止
        else:
            peak_end_volume = self.current_volume
            end_reason = "signal_drop"  # 峰由信号下降终止

        peak_width = peak_end_volume - self.peak_start_volume

        # 计算峰高和峰面积
        if len(self.peak_start_buffer) > 0:
            peak_max = max(self.peak_start_buffer)
            peak_area = sum(self.peak_start_buffer) * (peak_width / len(self.peak_start_buffer))
        else:
            peak_max = 0
            peak_area = 0

        self.detected_peaks.append({
            'id': self.total_peaks + 1,
            'start': self.peak_start_volume,
            'end': peak_end_volume,
            'width': peak_width,
            'max_height': peak_max - self.current_baseline,
            'area': peak_area,
            'end_reason': end_reason,
            'saddle': is_saddle_end,
            'time': time.time(),
            'tubes_id': self.current_peak_tubes_intid.copy()  # 记录当前峰对应的试管列表
        })

        self.current_peak_tubes_intid = []
        self.total_peaks += 1

    def detect_peak(self, signal_value):
        """
        改进的峰检测算法，包含重叠峰鞍点检测功能

        :param signal_value: 当前信号值
        :return: 布尔值，表示是否检测到峰
        """
        # 1. 原始信号缓存
        self.raw_buffer.append(signal_value)

        # 2. 信号平滑处理
        if len(self.raw_buffer) >= self.SG_WINDOW:
            try:
                smoothed = savgol_filter(list(self.raw_buffer)[-self.SG_WINDOW:],
                                         self.SG_WINDOW, self.SG_ORDER)[-1]
            except:
                smoothed = signal_value
        else:
            smoothed = signal_value

        self.smoothed_buffer.append(smoothed)

        # 3. 更新基线
        self.update_baseline(smoothed)

        # 4. 阈值计算
        standard_threshold = self.current_baseline + self.K_FACTOR * self.baseline_std
        sensitive_threshold = self.current_baseline + (
                self.K_FACTOR * self.SENSITIVE_THRESHOLD_FACTOR) * self.baseline_std
        signal_diff = smoothed - self.current_baseline

        # 5. 峰检测逻辑
        if not self.peak_detected:
            # 检测峰起始
            if smoothed > sensitive_threshold and self._has_rising_trend(self.SHORT_TREND_WINDOW):
                self.peak_detected = True
                self.peak_start_volume = self.current_volume
                self.peak_start_buffer.clear()
                self.peak_start_buffer.append(smoothed)
                # 重置鞍点检测相关变量
                self.saddle_candidate_count = 0
                self.saddle_detected = False

                # 当前试管加入峰对应试管列表
                # self.current_peak_tubes_intid.append(self.int_tube_id_now)

                return True
        else:
            self.peak_start_buffer.append(smoothed)

            # 鞍点检测部分
            if self.enable_saddle_detection and len(self.peak_start_buffer) >= self.SADDLE_WINDOW:
                if not self.saddle_detected and self._detect_saddle_point(
                        window=self.SADDLE_WINDOW,
                        significance_factor=self.SADDLE_SIGNIFICANCE):

                    self._record_peak(is_saddle_end=True)


                    # 从鞍点位置开始新峰
                    self.peak_start_volume = self.current_volume
                    self.peak_start_buffer.clear()
                    self.peak_start_buffer.append(smoothed)

                    # 重置鞍点检测状态但保持峰检测状态
                    self.saddle_detected = False
                    self.saddle_candidate_count = 0
                    self.peak_detected = True

                    return True


            # 峰结束检测（仅在未检测到鞍点时进行）
            if smoothed < standard_threshold and self._has_falling_trend(self.SHORT_TREND_WINDOW):
                self.peak_detected = False
                self._record_peak(is_saddle_end=False)
                self.post_peak_buffer = self.POST_PEAK_BUFFER_SIZE
                # 重置鞍点相关状态
                self.saddle_detected = False
                self.saddle_candidate_count = 0

                return False

        return self.peak_detected

    def experiment_end(self):
        if self.peak_detected:
            # 如果实验结束时仍在峰状态，记录当前峰
            self._record_peak(is_saddle_end=False)
            self.peak_detected = False


    def _has_rising_trend(self, window=5):
        """
        改进的上升趋势检测

        :param window: 检测窗口大小，默认5，增大提高稳定性但降低响应速度
        :return: 布尔值，表示是否检测到上升趋势
        """
        if len(self.smoothed_buffer) < window:
            return False

        # 获取最近数据点
        recent = list(self.smoothed_buffer)[-window:]

        # 短期斜率计算
        short_slope = (recent[-1] - recent[-2])
        # 中期斜率计算
        mid_slope = (recent[-1] - recent[0]) / (window - 1)

        # 组合条件：当前点高于过去平均值，且短期和中期都有上升趋势
        return (recent[-1] > np.mean(recent) and
                short_slope > 0 and mid_slope > 0)

    def _has_falling_trend(self, window=5):
        """
        改进的下降趋势检测

        :param window: 检测窗口大小，默认5，增大提高稳定性但降低响应速度
        :return: 布尔值，表示是否检测到下降趋势
        """
        if len(self.smoothed_buffer) < window:
            return False

        recent = list(self.smoothed_buffer)[-window:]

        # 计算连续点的下降比例
        falling_count = sum(1 for i in range(1, len(recent)) if recent[i] < recent[i - 1])

        # 如果超过70%的点在下降，则判定为下降趋势
        return falling_count >= int(self.FALLING_TREND_THRESHOLD * (window - 1))

    def _detect_saddle_point(self, window=15, significance_factor=1.5):
        """
        使用三区域平均法检测鞍点，更稳定抗噪

        参数:
        window: 分析窗口大小（建议为3的倍数）
        significance_factor: 鞍点判定的显著性因子
        """
        # 确保窗口大小为3的倍数
        window = max(9, window)
        if window % 3 != 0:
            window = window + (3 - window % 3)

        # 常量和阈值定义
        MIN_SADDLE_DISTANCE = 25  # 最小鞍点间距(mL)
        signal_level = max(self.smoothed_buffer) if self.smoothed_buffer else 0
        base_threshold = max(0.002, self.baseline_std * 1.2)
        depth_threshold = max(base_threshold, signal_level * 0.01)

        print(f"=== 鞍点检测调试 (体积:{self.current_volume:.2f}mL) ===")

        # 检查不应期
        if hasattr(self, 'last_saddle_volume') and self.last_saddle_volume > 0:
            volume_since_last = self.current_volume - self.last_saddle_volume
            if volume_since_last < MIN_SADDLE_DISTANCE:
                print(f"距离上次鞍点仅{volume_since_last:.2f}mL < {MIN_SADDLE_DISTANCE}mL，跳过检测")
                return False

        # 数据点检查
        if len(self.smoothed_buffer) < window:
            print("缓冲区数据不足，跳过鞍点检测")
            return False

        # 获取分析数据
        data = list(self.smoothed_buffer)[-window:]
        region_size = window // 3

        # 计算三个区域的平均值
        region_averages = []
        best_saddle = None
        best_significance = 0

        for i in range(len(data) - window + 1):
            # 计算三个连续区域的平均值
            region1 = np.mean(data[i:i + region_size])
            region2 = np.mean(data[i + region_size:i + 2 * region_size])
            region3 = np.mean(data[i + 2 * region_size:i + 3 * region_size])

            # 检查鞍点特征：中间区域低于两侧
            if region2 < region1 and region2 < region3:
                saddle_depth = region1 - region2
                right_rise = region3 - region2

                # 验证条件
                if (saddle_depth > depth_threshold and
                        right_rise > base_threshold and
                        right_rise / saddle_depth > 0.8):

                    # 计算显著性
                    significance = saddle_depth / self.baseline_std if self.baseline_std > 0 else 0

                    # 更新最佳鞍点
                    if significance > best_significance:
                        best_significance = significance
                        best_saddle = {
                            'depth': saddle_depth,
                            'rise': right_rise,
                            'ratio': right_rise / saddle_depth,
                            'significance': significance,
                            'index': i + region_size
                        }

        # 检查是否找到符合条件的鞍点
        if best_saddle and best_saddle['significance'] >= significance_factor:
            print(f"成功检测到鞍点! 体积:{self.current_volume:.2f}mL")
            self.saddle_detected = True
            self.last_saddle_volume = self.current_volume
            self.last_saddle_time = time.time()

            # 记录鞍点信息 - 添加signal字段
            if not hasattr(self, 'detected_saddles'):
                self.detected_saddles = []

            # 确保包含signal字段
            signal_value = self.smoothed_buffer[-1]  # 获取当前平滑信号值
            self.detected_saddles.append({
                'volume': self.current_volume,
                'signal': signal_value,  # 添加这个字段解决KeyError
                'depth': best_saddle['depth'],
                'rise': best_saddle['rise'],
                'significance': best_saddle['significance'],
                'time': time.time()
            })

            return True

        return False


    def update_signal(self, signal_value, volume_increment=0.02):
        """
        更新信号并处理峰检测和梯度调整，扩展版

        :param signal_value: 当前检测器读数，表示色谱信号强度
        :param volume_increment: 每次更新的体积增量(mL)，默认0.02
        :return: 包含详细状态信息的字典
        """
        result = super().update_signal(signal_value, volume_increment)
        # 添加其他信息到结果字典
        result['threshold'] = self.current_baseline + self.K_FACTOR * self.baseline_std
        result['sensitive_threshold'] = self.current_baseline + (
                    self.K_FACTOR * self.SENSITIVE_THRESHOLD_FACTOR) * self.baseline_std
        result['baseline'] = self.current_baseline
        result['baseline_std'] = self.baseline_std
        result['smoothed'] = self.smoothed_buffer[-1] if self.smoothed_buffer else signal_value
        return result

    def set_saddle_detection(self, enable=True, window=10, significance=1.5, confirm_count=3):
        """
        设置鞍点检测参数

        :param enable: 是否启用鞍点检测
        :param window: 鞍点检测窗口大小
        :param significance: 鞍点显著性因子
        :param confirm_count: 确认鞍点需要连续检测到的次数
        :return: 字典，包含当前鞍点检测设置
        """
        self.enable_saddle_detection = enable
        self.SADDLE_WINDOW = max(5, window)  # 确保窗口至少为5
        self.SADDLE_SIGNIFICANCE = max(1.0, significance)  # 确保显著性至少为1.0
        self.SADDLE_CONFIRM_COUNT = max(1, confirm_count)  # 至少需要1次确认

        # 重置鞍点检测状态
        self.saddle_candidate_count = 0
        self.saddle_detected = False

        print(f"鞍点检测: {'启用' if enable else '禁用'}, "
              f"窗口: {self.SADDLE_WINDOW}, "
              f"显著性: {self.SADDLE_SIGNIFICANCE}, "
              f"确认次数: {self.SADDLE_CONFIRM_COUNT}")

        return {
            'enabled': self.enable_saddle_detection,
            'window': self.SADDLE_WINDOW,
            'significance': self.SADDLE_SIGNIFICANCE,
            'confirm_count': self.SADDLE_CONFIRM_COUNT
        }

               # vertical_point = {
               #      "time_start": time_start_line,
               #      "time_end": time_end,
               #      "module_index": module_index,
               #      "tube_index": self.tube_index
               #  }
               #
               #  self.vertical_data.append(vertical_point)
               #  socketio.emit('new_point', {'point': vertical_point})
               #  await self.switch_to_next_tube()
               #  p_c.change_tube(vertical_point)

    def change_tube(self, last_tube):
        print('last_tube_index:', last_tube)
        self.tubes_list.append(last_tube.copy())
        self.int_tube_id_now = last_tube['module_index'] * 10 + last_tube['tube_index'] + 1
        #self.tube_index_now = tube_index.copy()
        if self.peak_detected:
            self.current_peak_tubes_intid.append(self.int_tube_id_now)


    def get_tubes_by_peak_id(self,peak_id):
        """
        根据峰ID获取对应的试管列表

        :param peak_id: 峰ID
        :return: 试管列表
        """
        for peak in self.detected_peaks:
            if peak['id'] == peak_id:
                try:
                    return [self.tubes_list[tube_id] for tube_id in peak['tubes_id']]
                except IndexError: # 可能缺少最后一根试管的信息
                    self.tubes_list.append({'module_index': self.int_tube_id_now // 10,
                                            'tube_index': self.int_tube_id_now % 10,
                                            "time_start": None,
                                            "time_end": None,
                                            })  # 确保列表不为空
                    return [self.tubes_list[tube_id] for tube_id in peak['tubes_id']]
        return []

    def get_tubes_by_peak_area(self, peak_area_rank):
        """
        根据峰面积排序获取对应的试管列表

        :param peak_area_rank: 峰面积排序序号（1表示面积最大的峰）
        :return: 试管列表
        """
        # 根据面积排序峰
        sorted_peaks = sorted(self.detected_peaks, key=lambda x: x.get('area', 0), reverse=True)

        # 确保序号在有效范围内
        if peak_area_rank <= 0 or peak_area_rank > len(sorted_peaks):
            return []

        # 获取对应排名的峰
        target_peak = sorted_peaks[peak_area_rank - 1]

        try:
            return [self.tubes_list[tube_id] for tube_id in target_peak['tubes_id']]
        except IndexError:  # 可能缺少最后一根试管的信息
            self.tubes_list.append({
                'module_index': self.int_tube_id_now // 10,
                'tube_index': self.int_tube_id_now % 10,
                "time_start": None,
                "time_end": None,
            })  # 确保列表不为空
            return [self.tubes_list[tube_id] for tube_id in target_peak['tubes_id']]


def generate_signal(total_time_points=1200, flow_rate=35, time_increment=1 / 60):
    """
    生成更真实的色谱信号数据，专门针对高流速系统优化

    :param total_time_points: 总采样点数，默认1200个点(20分钟×60秒/分钟)
    :param flow_rate: 流速(mL/min)，默认35 mL/min
    :param time_increment: 时间增量(min)，默认1/60 min(1秒)
    :return: 信号值列表，体积值列表，时间值列表
    """
    # 全局常量定义
    NOISE_LEVEL = 0.003  # 基线噪声水平
    DRIFT_AMPLITUDE = 0.008  # 漂移幅度
    BASELINE_OFFSET = 0.02  # 基线偏移值
    DRIFT_FREQUENCY_1 = 0.03  # 主漂移频率
    DRIFT_FREQUENCY_2 = 0.01  # 次漂移频率

    # 峰参数(中心位置mL, 高度, 宽度系数)
    PEAK_PARAMS = [
        (120, 0.25, 20),  # 第一个峰：约3.5个CV处
        (250, 0.3, 22),  # 第二个峰：约7.3个CV处
        (400, 0.22, 25)  # 第三个峰：约11.8个CV处
    ]

    signals = []
    volumes = []
    times = []

    for i in range(total_time_points):
        time_min = i * time_increment
        volume = time_min * flow_rate

        # 基线漂移 - 使用组合正弦函数模拟真实基线漂移
        baseline_drift = DRIFT_AMPLITUDE * np.sin(DRIFT_FREQUENCY_1 * time_min) + DRIFT_AMPLITUDE / 2 * np.sin(
            DRIFT_FREQUENCY_2 * time_min)
        noise = NOISE_LEVEL * np.random.normal(0, 1)

        # 基础信号 = 基线偏移 + 漂移 + 噪声
        signal = BASELINE_OFFSET + baseline_drift + noise

        # 添加峰
        for center, height, width in PEAK_PARAMS:
            # 只在相关区域计算峰贡献
            if abs(volume - center) < width * 2:
                # 使用高斯函数作为峰形状
                peak_contribution = height * np.exp(-0.5 * ((volume - center) / (width / 2)) ** 2)
                signal += peak_contribution

        signals.append(signal)
        volumes.append(volume)
        times.append(time_min)

    return signals, volumes, times



from matplotlib.animation import FuncAnimation

def run_simulation_real_system_video(data=None):
    """
    运行基于真实色谱体系参数的模拟
    - 流速：35 mL/min
    - 柱体积：34 mL
    - 采样频率：1s (0.0167 min)
    - 总运行时间：20 min
    """
    time_increment = 1 / 60  # 1秒 = 1/60分钟
    flow_rate = 35  # mL/min
    total_time_points = int(20 / time_increment)  # 20分钟共1200个采样点
    if not data:
        signals, volumes, times = generate_signal(
            total_time_points=total_time_points,
            flow_rate=flow_rate,
            time_increment=time_increment
        )
    else:
        signals = data

    controller = PrepChromController(
        start_ratio=100,
        end_ratio=50,
        n1_volumes=2,
        gradient_rate=5,
        peak_threshold=0.1,
        column_volume=34,
        sg_window=21,
        sg_order=3,
        baseline_window=180,
        k_factor=3.0
    )

    results = []
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    vol, sig, smt, bl, thr, sens_thr, ratios, states = [], [], [], [], [], [], [], []

    def update(frame):
        if frame >= len(signals):
            return
        signal = signals[frame]
        volume_increment = flow_rate * time_increment
        result = controller.update_signal(signal, volume_increment)
        results.append(result)

        vol.append(result['volume'])
        sig.append(result['signal'])
        smt.append(result['smoothed'])
        bl.append(result['baseline'])
        thr.append(result['threshold'])
        sens_thr.append(result.get('sensitive_threshold', result['threshold'] * 0.9))
        ratios.append(result['ratio'])
        states.append(result['state'])

        ax1.clear()
        ax1.plot(vol, sig, 'b-', alpha=0.4, label='原始信号')
        ax1.plot(vol, smt, 'c-', linewidth=1.5, label='平滑信号')
        ax1.plot(vol, bl, 'g-', linewidth=1.5, label='动态基线')
        ax1.plot(vol, thr, 'r--', linewidth=1.5, label='主阈值')
        ax1.plot(vol, sens_thr, 'm:', linewidth=1.0, label='灵敏阈值')

        peaks = [i for i, r in enumerate(results) if r['peak_detected']]
        ax1.scatter([vol[i] for i in peaks], [sig[i] for i in peaks],
                    c='red', s=20, label='检测到的峰')

        for peak in controller.detected_peaks:
            ax1.axvspan(peak['start'], peak['end'], alpha=0.1, color='orange')

        ax1.set_ylabel('信号强度')
        ax1.set_title('色谱信号与峰检测')
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)

        ax2.clear()
        ax2.plot(vol, ratios, 'g-', label='洗脱剂A比例 (%)')
        ax2.set_xlabel('体积 (mL)')
        ax2.set_ylabel('洗脱剂A比例 (%)')
        ax2.set_title('梯度洗脱曲线')
        ax2.legend()
        ax2.grid(True)

    ani = FuncAnimation(fig, update, frames=len(signals), interval=50, repeat=False)
    plt.tight_layout()
    plt.show()

    print("\n检测统计:")
    print(f"总峰数: {controller.total_peaks}")
    for i, peak in enumerate(controller.detected_peaks):
        print(f"峰{i + 1}: 起始={peak['start']:.2f}mL, 结束={peak['end']:.2f}mL, 宽度={peak['width']:.2f}mL")


def run_simulation_real_system(data=None):
    """
    运行基于真实色谱体系参数的模拟，增加鞍点检测功能
    - 流速：35 mL/min
    - 柱体积：34 mL
    - 采样频率：1s (0.0167 min)
    - 总运行时间：20 min
    """
    time_increment = 1 / 60  # 1秒 = 1/60分钟
    flow_rate = 35  # mL/min
    total_time_points = int(20 / time_increment)  # 20分钟共1200个采样点
    if not data:
        # 生成测试信号，使用真实系统参数
        signals, volumes, times = generate_signal(
            total_time_points=total_time_points,
            flow_rate=flow_rate,
            time_increment=time_increment
        )
    else:
        # 如果提供了数据，则直接使用
        signals = data



    # 初始化控制器，参数针对高流速大柱体积系统优化
    controller = PrepChromController(
        start_ratio=80,
        end_ratio=50,
        n1_volumes=2,
        gradient_rate=1.5,
        peak_threshold=0.1,
        column_volume=34,  # 真实柱体积
        sg_window=21,  # 增大平滑窗口，适应更宽的峰
        sg_order=3,
        baseline_window=180,  # 增大基线窗口
        k_factor=20  # 调整阈值系数，提高检测灵敏度
    )

    # 启用鞍点检测
    controller.set_saddle_detection(enable=True, window=15, significance=1.2)

    # 运行控制器处理所有信号点
    results = []
    for i, signal in enumerate(signals):
        # 每个采样点的体积增量 = 流速 × 时间增量
        volume_increment = flow_rate * time_increment
        results.append(controller.update_signal(signal, volume_increment))
        # print(results)

    # 可视化结果
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    # 信号图 - 包含详细信息
    vol = [r['volume'] for r in results]
    sig = [r['signal'] for r in results]
    smt = [r['smoothed'] for r in results]
    bl = [r['baseline'] for r in results]
    thr = [r['threshold'] for r in results]
    sens_thr = [r.get('sensitive_threshold', r['threshold'] * 0.9) for r in results]

    # 绘制信号和阈值
    ax1.plot(vol, sig, 'b-', alpha=0.4, label='原始信号')
    ax1.plot(vol, smt, 'c-', linewidth=1.5, label='平滑信号')
    ax1.plot(vol, bl, 'g-', linewidth=1.5, label='动态基线')
    ax1.plot(vol, thr, 'r--', linewidth=1.5, label='主阈值')
    ax1.plot(vol, sens_thr, 'm:', linewidth=1.0, label='灵敏阈值')

    # 标记检测到的峰
    peaks = [i for i, r in enumerate(results) if r['peak_detected']]
    ax1.scatter([vol[i] for i in peaks], [sig[i] for i in peaks],
                c='red', s=20, label='检测到的峰')

    # 添加峰区域标记，区分普通峰和鞍点结束的峰
    print(controller.detected_peaks)
    for peak in controller.detected_peaks:
        # 如果峰是由鞍点结束的，使用不同颜色标记
        is_saddle_end = peak.get('saddle', False)
        color = 'pink' if is_saddle_end else 'orange'
        ax1.axvspan(peak['start'], peak['end'], alpha=0.15, color=color)

        # 添加峰ID标签
        ax1.text((peak['start'] + peak['end']) / 2, max(sig) * 0.85,
                 f"峰{peak.get('id', '')}", fontsize=9, ha='center')

        # 标记峰终止类型
        if is_saddle_end:
            ax1.text(peak['end'], max(sig) * 0.8, "△", fontsize=9, ha='center', color='red')

    # 标记检测到的鞍点
    if hasattr(controller, 'detected_saddles') and controller.detected_saddles:
        saddle_x = [s['volume'] for s in controller.detected_saddles]
        saddle_y = [s['signal'] for s in controller.detected_saddles]
        ax1.scatter(saddle_x, saddle_y, c='red', marker='^', s=80, alpha=0.7, label='鞍点')

        # 为每个鞍点添加标签
        for i, (x, y) in enumerate(zip(saddle_x, saddle_y)):
            ax1.text(x, y * 1.1, f"鞍点{i + 1}", fontsize=8, ha='center', color='red')


    ax1.set_ylabel('信号强度')
    ax1.set_title('色谱信号与峰检测 (含鞍点识别)')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)

    # 标记柱体积
    for i in range(1, int(max(vol) / controller.COLUMN_VOLUME) + 1):
        ax1.axvline(x=i * controller.COLUMN_VOLUME, color='gray', linestyle=':', alpha=0.5)
        ax1.text(i * controller.COLUMN_VOLUME, max(sig) * 0.9, f'{i} CV',
                 fontsize=8, ha='center', bbox=dict(facecolor='white', alpha=0.5))

    # 梯度曲线图
    ratios = [r['ratio'] for r in results]
    states = [r['state'] for r in results]

    ax2.plot(vol, ratios, 'g-', label='洗脱剂A比例 (%)')
    ax2.set_xlabel('体积 (mL)')
    ax2.set_ylabel('洗脱剂A比例 (%)')
    ax2.set_title('梯度洗脱曲线')
    ax2.legend()
    ax2.grid(True)

    # 添加状态变化标记
    state_changes = []
    for i in range(1, len(states)):
        if states[i] != states[i - 1]:
            state_changes.append((vol[i], ratios[i], states[i]))

    for v, r, state in state_changes:
        ax2.plot(v, r, 'ro', markersize=6)
        ax2.text(v, r + 2, state, fontsize=8, ha='center',
                 bbox=dict(facecolor='white', alpha=0.7))

    # 标记柱体积
    for i in range(1, int(max(vol) / controller.COLUMN_VOLUME) + 1):
        ax2.axvline(x=i * controller.COLUMN_VOLUME, color='gray', linestyle=':', alpha=0.5)

    # 添加第二个x轴显示时间
    ax3 = ax2.twiny()
    ax3.set_xlim(ax2.get_xlim())
    time_ticks = np.arange(0, 21, 2)  # 每2分钟标记一次，显示0-20分钟
    ax3.set_xticks([t * flow_rate for t in time_ticks])
    ax3.set_xticklabels([str(int(t)) for t in time_ticks])
    ax3.set_xlabel('时间 (分钟)')

    plt.tight_layout()
    plt.show()

    # 打印峰统计信息
    print("\n峰检测统计:")
    print(f"总峰数: {controller.total_peaks}")
    for i, peak in enumerate(controller.detected_peaks):
        end_reason = "鞍点终止" if peak.get('saddle', False) else "信号下降终止"
        print(f"峰{peak.get('id', i + 1)}: 起始={peak['start']:.2f}mL, 结束={peak['end']:.2f}mL, "
              f"宽度={peak['width']:.2f}mL, 终止方式={end_reason}")

    # 打印鞍点统计信息
    if hasattr(controller, 'detected_saddles') and controller.detected_saddles:
        print("\n鞍点检测统计:")
        for i, saddle in enumerate(controller.detected_saddles):
            print(f"鞍点{i + 1}: 位置={saddle['volume']:.2f}mL, 信号值={saddle['signal']:.5f}, "
                  f"显著性={saddle.get('significance', 'N/A')}")

    return controller

def manual_controls():
    """测试手动控制功能：手动梯度调整和manual hold"""
    print("\n===== 测试手动控制功能 =====")

    # 根据采样频率和总时间计算总采样点数
    time_increment = 1 / 60  # 1秒 = 1/60分钟
    flow_rate = 35  # mL/min
    signals, volumes, times = generate_signal(total_time_points=1200)

    # 初始化控制器
    controller = GradientElutionController(
        start_ratio=100,
        end_ratio=50,
        gradient_rate=5,
        peak_threshold=0.1,
        column_volume=34,
        peak_hold_signal_threshold=0.15
    )

    # 运行前半部分常规梯度
    results = []
    halfway = len(signals) // 2
    for i in range(halfway):
        volume_increment = flow_rate * time_increment
        result = controller.update_signal(signals[i], volume_increment)
        results.append(result)

    print(
        f"半程运行状态 - 体积: {controller.current_volume:.2f}mL, 比例: {controller.current_ratio:.1f}%, 状态: {controller.state}")

    # 测试1：手动修改梯度速率
    print("\n1. 测试手动调整梯度速率")
    old_rate = controller.GRADIENT_RATE
    new_rate = controller.set_gradient_rate(10.0)  # 调整为原来的2倍
    print(f"梯度速率: {old_rate} -> {new_rate} %/CV")

    # 测试2：手动修改溶剂比例
    print("\n2. 测试手动设置溶剂比例")
    old_ratio = controller.current_ratio
    new_ratio = controller.set_current_ratio(85.0)  # 手动设置为85%
    print(f"溶剂比例: {old_ratio:.1f}% -> {new_ratio:.1f}%")

    # 再运行一段时间
    for i in range(200):
        volume_increment = flow_rate * time_increment
        result = controller.update_signal(signals[halfway + i], volume_increment)
        results.append(result)

    print(
        f"调整后运行状态 - 体积: {controller.current_volume:.2f}mL, 比例: {controller.current_ratio:.1f}%, 状态: {controller.state}")

    # 测试3：开启手动hold
    print("\n3. 测试manual hold功能")
    old_state = controller.state
    new_state = controller.set_manual_hold(True)
    print(f"状态变化: {old_state} -> {new_state}")

    # 在manual hold状态下运行一段时间
    hold_results = []
    for i in range(100):
        volume_increment = flow_rate * time_increment
        result = controller.update_signal(signals[halfway + 200 + i], volume_increment)
        hold_results.append(result)

    # 验证比例是否保持不变
    ratio_before_hold = results[-1]['ratio']
    ratio_during_hold = hold_results[-1]['ratio']
    print(f"Manual hold期间比例: {ratio_before_hold:.1f}% -> {ratio_during_hold:.1f}%")
    print(f"Manual hold期间体积变化: {results[-1]['volume']:.2f}mL -> {hold_results[-1]['volume']:.2f}mL")

    # 测试4：关闭manual hold
    print("\n4. 测试关闭manual hold")
    old_state = controller.state
    new_state = controller.set_manual_hold(False)
    print(f"状态变化: {old_state} -> {new_state}")

    # 继续运行
    after_hold_results = []
    for i in range(100):
        volume_increment = flow_rate * time_increment
        result = controller.update_signal(signals[halfway + 300 + i], volume_increment)
        after_hold_results.append(result)

    # 验证比例是否继续变化
    ratio_after_hold = after_hold_results[-1]['ratio']
    print(f"解除manual hold后比例变化: {ratio_during_hold:.1f}% -> {ratio_after_hold:.1f}%")

    # 测试5：PeakHold阈值调整
    print("\n5. 测试PeakHold阈值调整")
    old_threshold = controller.PEAK_HOLD_SIGNAL_THRESHOLD
    old_enabled = getattr(controller, 'use_signal_threshold', True)
    new_threshold = controller.set_peak_hold_threshold(0.2, enable=True)
    print(f"峰保持阈值: {old_threshold:.3f} -> {new_threshold:.3f}")
    print(f"峰保持条件启用状态: {old_enabled} -> {getattr(controller, 'use_signal_threshold', True)}")

    # 绘制测试结果
    # 合并所有结果
    all_results = results + hold_results + after_hold_results

    # 可视化结果
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    # 提取数据
    vol = [r['volume'] for r in all_results]
    sig = [r['signal'] for r in all_results]
    ratios = [r['ratio'] for r in all_results]
    states = [r['state'] for r in all_results]

    # 绘制信号
    ax1.plot(vol, sig, 'b-', label='信号')
    ax1.set_ylabel('信号强度')
    ax1.set_title('测试手动控制功能 - 信号')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 绘制梯度曲线
    ax2.plot(vol, ratios, 'g-', label='洗脱剂A比例 (%)')
    ax2.set_xlabel('体积 (mL)')
    ax2.set_ylabel('洗脱剂A比例 (%)')
    ax2.set_title('测试手动控制功能 - 梯度曲线')

    # 标记手动操作点
    halfway_point = results[halfway]['volume']
    ax2.axvline(x=halfway_point, color='blue', linestyle='--', alpha=0.5, label='开始手动调整')
    ax2.axvline(x=results[-1]['volume'], color='red', linestyle='--', alpha=0.5, label='manual hold开启')
    ax2.axvline(x=hold_results[-1]['volume'], color='green', linestyle='--', alpha=0.5, label='manual hold关闭')

    # 标记不同状态区域
    state_changes = []
    for i in range(1, len(states)):
        if states[i] != states[i - 1]:
            state_changes.append((vol[i], states[i]))

    for v, state in state_changes:
        ax2.axvline(x=v, color='purple', linestyle=':', alpha=0.5)
        ax2.text(v, ratios[0] - 5, state, fontsize=8, rotation=90)

    ax2.legend()
    ax2.grid(True)

    plt.tight_layout()
    plt.show()

    return controller


def run_overlapping_peaks_test():
    """测试重叠峰检测功能"""
    print("\n===== 测试重叠峰检测功能 =====")

    # 生成带有重叠峰的测试数据
    signals = []
    volumes = []
    times = []

    time_increment = 1 / 60  # 1秒
    flow_rate = 35  # mL/min
    total_points = 1200

    # 生成信号数据
    for i in range(total_points):
        time_min = i * time_increment
        volume = time_min * flow_rate

        # 基础信号
        signal = 0.02 + 0.003 * np.random.normal()

        # 添加重叠峰
        # 第一个峰
        if 300 <= i <= 400:
            peak1 = 0.3 * np.exp(-((i - 350) / 25) ** 2)
            signal += peak1

        # 第二个峰 - 与第一个峰部分重叠
        if 360 <= i <= 460:
            peak2 = 0.25 * np.exp(-((i - 410) / 25) ** 2)
            signal += peak2

        # 第三个峰 - 完全重叠的双峰
        if 600 <= i <= 700:
            peak3a = 0.4 * np.exp(-((i - 650) / 15) ** 2)
            peak3b = 0.3 * np.exp(-((i - 670) / 15) ** 2)
            signal += peak3a + peak3b

        signals.append(signal)
        volumes.append(volume)
        times.append(time_min)

    # 初始化控制器
    controller = PrepChromController(
        start_ratio=100,
        end_ratio=50,
        n1_volumes=2,
        gradient_rate=5,
        peak_threshold=0.05,
        column_volume=34,
        sg_window=11,  # 减小滤波窗口以保留更多峰细节
        sg_order=2,
        baseline_window=180,
        k_factor=10  # 降低阈值系数以提高峰检测灵敏度
    )

    # 启用鞍点检测
    controller.set_saddle_detection(enable=True, window=6, significance=1.2,confirm_count=1)

    # 处理信号
    results = []
    for i, signal in enumerate(signals):
        volume_increment = flow_rate * time_increment
        result = controller.update_signal(signal, volume_increment)
        results.append(result)

    # 可视化结果
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    # 绘制信号和基线
    vol = [r['volume'] for r in results]
    sig = [r['signal'] for r in results]
    smt = [r['smoothed'] for r in results]
    bl = [r['baseline'] for r in results]

    ax1.plot(vol, sig, 'b-', alpha=0.4, label='原始信号')
    ax1.plot(vol, smt, 'c-', linewidth=1.5, label='平滑信号')
    ax1.plot(vol, bl, 'g-', linewidth=1.5, label='动态基线')

    # 标记检测到的峰和鞍点
    for peak in controller.detected_peaks:
        color = 'orange' if not peak.get('saddle', False) else 'pink'
        ax1.axvspan(peak['start'], peak['end'], alpha=0.1, color=color)
        ax1.text((peak['start'] + peak['end']) / 2, max(sig) * 0.9,
                 f"峰{peak['id']}", fontsize=10, ha='center')

        # 标记峰结束类型
        end_marker = "△" if peak.get('saddle', False) else "▽"
        ax1.text(peak['end'], max(sig) * 0.8, end_marker, fontsize=12, ha='center')

    # 标记鞍点
    for saddle in controller.detected_saddles:
        ax1.plot(saddle['volume'], saddle['signal'], 'r^', markersize=8)
        ax1.text(saddle['volume'], saddle['signal'] * 1.1, "鞍点",
                 fontsize=8, ha='center', rotation=0, color='red')

    ax1.set_ylabel('信号强度')
    ax1.set_title('重叠峰检测 - 鞍点识别')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)

    # 绘制梯度曲线
    ratios = [r['ratio'] for r in results]
    ax2.plot(vol, ratios, 'g-', label='洗脱剂A比例 (%)')
    ax2.set_xlabel('体积 (mL)')
    ax2.set_ylabel('洗脱剂A比例 (%)')
    ax2.legend()
    ax2.grid(True)

    plt.tight_layout()
    plt.show()

    # 打印峰和鞍点信息
    print("\n检测到的峰:")
    for peak in controller.detected_peaks:
        end_type = "鞍点终止" if peak.get('saddle', False) else "信号下降终止"
        print(f"峰{peak['id']}: 起始={peak['start']:.2f}mL, 结束={peak['end']:.2f}mL, "
              f"宽度={peak['width']:.2f}mL, 终止方式={end_type}")

    print("\n检测到的鞍点:")
    for i, saddle in enumerate(controller.detected_saddles):
        print(f"鞍点{i + 1}: 位置={saddle['volume']:.2f}mL, 信号值={saddle['signal']:.5f}")

    return controller



if __name__ == "__main__":

    def time_to_seconds(time_str):
        """将时间字符串 (H:M:S) 转换为秒"""
        h, m, s = map(int, time_str.split(':'))
        return h * 3600 + m * 60 + s
    # 打开并读取数据
    f = open("data.txt", "r")
    data = eval(f.read())
    f.close()
    
    # print(data)

    # 转换数据
    processed_data = []
    for entry in data:
        seconds = time_to_seconds(entry['time'])
        value = float(entry['value'])  # 确保value是float类型
        # if value > 0.1:
        #     print(seconds, entry['value'])
        # elif value < 0.1:
        #     print('-----', seconds, entry['value'])
            # processed_data.append([seconds, value])
        processed_data.append({'time': seconds, 'value': value})
        data = [d['value'] for d in processed_data]

    print("色谱峰检测系统 - 真实参数模拟版")
    run_simulation_real_system(data)

    # print("测试手动控制功能...")
    # manual_controls()
    #
    # print("测试重叠峰检测功能...")
    # run_overlapping_peaks_test()