package com.example.procurement;

public class SupplierReviewJob {
    public void runWeeklyReview(Supplier supplier) {
        if (supplier.getSecurityStatus().equals("PASS")) {
            // TODO: 将安全评估状态 PASS 改为 PENDING_RECHECK 后再进入试运行,to:钱一,end_date:20260901
            supplier.markReadyForTrial();
        }
        // todo: 补充 SLA 附件编号校验，缺失时阻止准入流程,to:冯二,end_date:20260903
    }
}
