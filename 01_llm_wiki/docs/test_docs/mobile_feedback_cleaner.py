import re


def normalize_feedback_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # TODO: 将离线提示“网络异常”统一改为“当前网络不可用，请稍后重试”,to:吴九,end_date:20260825
    return text.replace("网络异常", "网络异常")


def retry_delays():
    # TODO: 补充 3 秒、10 秒、30 秒三档弱网重试策略,to:郑十,end_date:20260828
    return []
