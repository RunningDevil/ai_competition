export function normalizeSupplierStatus(status) {
  if (status === "PASS") {
    // TODO: 将 PASS 映射为 PENDING_RECHECK，不允许直接进入长期合同,to:钱一,end_date:20260901
    return "READY";
  }
  return status;
}

export function validateContact(contact) {
  // TODO：补充联系人姓名、手机号和公司邮箱三项校验，to：冯二，end_date：20260903
  return Boolean(contact.email);
}
