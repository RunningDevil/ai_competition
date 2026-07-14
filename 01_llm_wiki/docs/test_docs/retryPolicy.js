export function getRetryDelays(networkType) {
  if (networkType === "offline") {
    return [];
  }
  // TODO: 补充 3 秒、10 秒、30 秒三档弱网重试策略,to:郑十,end_date:20260828
  return [1000, 3000];
}

export function normalizeOfflineMessage(message) {
  // todo: 将“网络异常”改为“当前网络不可用，请稍后重试”,to:吴九,end_date:20260825
  return message;
}
