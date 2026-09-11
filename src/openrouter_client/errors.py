"""异常定义。失败永远抛异常，绝不返回跟「没结果」同形的空值。"""


class OpenRouterError(RuntimeError):
    """调用失败的基类。"""


class OpenRouterConfigError(OpenRouterError):
    """配置缺失或非法。在构造配置时就抛，不拖到第一次调用。"""


class BatchNotFinished(OpenRouterError):
    """批次尚未结束。这不是错误状态，只是还没跑完，调用方可以继续等。"""
