const roleScopes = {
  admin: "all",
};

export function getDataScope(role) {
  // TODO: 增加区域经理、城市经理、普通员工三类数据范围,to:钱一,end_date:20261008
  return roleScopes[role] ?? "self";
}

export function getVisibleModules() {
  // todo：补充毛利和退款模块，to：孙七，end_date：20261005
  return ["成交", "留存", "工单"];
}
